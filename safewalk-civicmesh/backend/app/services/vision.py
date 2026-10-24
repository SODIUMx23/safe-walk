"""Runnable, deterministic OpenCV baseline with explicitly limited semantics.

High-contrast overhead edges and dark ground discontinuities are CANDIDATES.
A monocular image does not provide sonar, drop depth, wire recall, or clearance.
No third-party model, proprietary endpoint, or fabricated detection is used.
"""
from __future__ import annotations

import base64
import math
import os
import re
import shutil
import struct
import subprocess
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "2000000")
import cv2
import numpy as np

from .ai_spatial import project_angles

cv2.setNumThreads(1)


def _jpeg_size(raw: bytes):
    if not raw.startswith(b"\xff\xd8"):
        raise ValueError("Only JPEG camera frames are accepted")
    pos = 2
    while pos + 4 <= len(raw):
        if raw[pos] != 255:
            raise ValueError("Malformed JPEG header")
        while pos < len(raw) and raw[pos] == 255:
            pos += 1
        if pos >= len(raw):
            break
        marker = raw[pos]
        pos += 1
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(raw):
            break
        length = struct.unpack(">H", raw[pos:pos + 2])[0]
        if length < 2:
            raise ValueError("Malformed JPEG segment")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 8 or pos + 7 > len(raw):
                break
            height, width = struct.unpack(">HH", raw[pos + 3:pos + 7])
            return width, height
        if marker == 0xDA:
            break
        pos += length
    raise ValueError("JPEG dimensions unavailable")


def decode_frame(encoded: str):
    if encoded.startswith("data:"):
        if not encoded.startswith("data:image/jpeg;base64,"):
            raise ValueError("Expected a JPEG data URI")
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Malformed base64 frame") from exc
    if len(raw) > 310000:
        raise ValueError("Camera frame exceeds 310 kB")
    width, height = _jpeg_size(raw)
    if min(width, height) < 16 or max(width, height) > 1280 or width * height > 1280 * 960:
        raise ValueError("Camera frames must be at most 1280 by 960 pixels")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode JPEG")
    return image, raw


def analyze_frame(image, pitch=0.0, calibrated=False, vertical_fov=54.0):
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    brightness = float(np.mean(gray))
    candidates = []
    if brightness < 25:
        return {"candidates": [], "brightness": round(brightness, 1), "quality": "LOW_LIGHT",
                "description": "The camera view is too dark for this visual baseline. Stop and use your usual mobility aid.",
                "ground_observation": "UNAVAILABLE", "head_observation": "UNAVAILABLE", "metric_depth_available": False}
    edges = cv2.Canny(gray, 65, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(35, w // 10),
                            minLineLength=w * .20, maxLineGap=w * .035)
    overhead_lines, crossing_rows = [], []
    if lines is not None:
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(int, line)
            if abs(y2 - y1) > .12 * abs(x2 - x1) + 2:
                continue
            cy = (y1 + y2) / (2 * h)
            box = {"x_min": max(0, min(x1, x2) / w), "x_max": min(1, max(x1, x2) / w),
                   "y_min": max(0, cy - .025), "y_max": min(1, cy + .025)}
            angle = project_angles(box, pitch, vertical_fov=vertical_fov)
            if calibrated and angle["in_headspace_cone"] and .1 < cy < .65:
                overhead_lines.append(box)
            if .55 < cy < .95:
                crossing_rows.append(round(cy * 20))
    if overhead_lines:
        candidate = max(overhead_lines, key=lambda b: b["x_max"] - b["x_min"])
        candidates.append({**candidate, "label": "overhead edge", "kind": "HEAD_LEVEL", "confidence": .62,
                           "source": "visual_candidate", "distance_m": None, "metric_height_verified": False})
    # Compare each central-ground dark region with its local surroundings.
    roi_top, roi_left, roi_right = int(h * .56), int(w * .2), int(w * .8)
    ground = gray[roi_top:int(h * .96), roi_left:roi_right]
    threshold = max(12, min(80, float(np.median(ground)) * .42))
    mask = (ground < threshold).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:2]:
        area = cv2.contourArea(contour)
        x, y, cw, ch = cv2.boundingRect(contour)
        fraction = area / (h * w)
        if .012 < fraction < .18 and cw > w * .15 and ch > h * .055:
            candidates.append({"x_min": (x + roi_left) / w, "y_min": (y + roi_top) / h,
                               "x_max": (x + cw + roi_left) / w, "y_max": (y + ch + roi_top) / h,
                               "label": "ground contrast change", "kind": "GROUND_VOID", "confidence": .58,
                               "source": "visual_candidate", "distance_m": None, "metric_drop_verified": False})
            break
    if any(c["kind"] == "GROUND_VOID" for c in candidates):
        description = "A possible ground surface change is visible. A shadow or dark patch can look similar; depth is not known. Stop and check with your cane."
    elif any(c["kind"] == "HEAD_LEVEL" for c in candidates):
        description = "A horizontal overhead edge is visible in the upward sector. Its height and clearance are not known."
    elif len(set(crossing_rows)) >= 4:
        description = "Several horizontal ground markings are visible, possibly crossing stripes. This does not establish a safe crossing or a distance."
    else:
        description = "No supported visual candidate was found. This does not mean the path is clear; this baseline cannot describe all objects."
    return {"candidates": candidates, "brightness": round(brightness, 1), "quality": "BASELINE_ONLY",
            "description": description, "ground_observation": "CANDIDATE" if any(c["kind"] == "GROUND_VOID" for c in candidates) else "NO_METRIC_SENSOR",
            "head_observation": "CANDIDATE" if overhead_lines else "NO_METRIC_SENSOR", "metric_depth_available": False}


def inspect_rupee(image):
    detector = cv2.QRCodeDetector()
    values = []
    try:
        found, decoded, _, _ = detector.detectAndDecodeMulti(image)
        if found:
            values = [text for text in decoded if text]
        if not values:
            text, _, _ = detector.detectAndDecode(image)
            if text:
                values = [text]
    except cv2.error:
        values = []
    if len(values) > 1:
        return {"mode": "QR", "status": "MULTIPLE_CODES", "speech": "Multiple QR codes are visible. Isolate the intended code before checking.", "can_pay": False}
    if values:
        parsed = urlparse(values[0][:4096])
        if parsed.scheme.lower() != "upi" or parsed.netloc.lower() != "pay":
            return {"mode": "QR", "status": "NOT_UPI", "speech": "This is not a supported UPI payment QR. No link has been opened.", "can_pay": False}
        query = parse_qs(parsed.query, max_num_fields=30)
        pa = query.get("pa", [""])[0]
        if len(query.get("pa", [])) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]{2,128}@[A-Za-z0-9.-]{2,64}", pa):
            return {"mode": "QR", "status": "INVALID_UPI", "speech": "The UPI address is invalid or ambiguous. Do not pay.", "can_pay": False}
        name = " ".join(query.get("pn", ["unnamed payee"])[0].split())[:80]
        amount = query.get("am", [None])[0]
        if amount is not None:
            try:
                val = Decimal(amount)
                if not val.is_finite() or not 0 < val <= 1000000 or val.as_tuple().exponent < -2:
                    raise InvalidOperation
                amount = str(val)
            except (InvalidOperation, ValueError):
                return {"mode": "QR", "status": "INVALID_AMOUNT", "speech": "The payment QR contains an invalid amount. Do not pay.", "can_pay": False}
        currency = query.get("cu", ["INR"])[0]
        if currency.upper() != "INR" or any(len(query.get(key, [])) > 1 for key in ("pn", "am", "cu")):
            return {"mode": "QR", "status": "AMBIGUOUS_FIELDS", "speech": "The payment QR has ambiguous or unsupported fields. Do not pay.", "can_pay": False}
        return {"mode": "UPI", "status": "UNVERIFIED_PAYEE", "payee_address": pa, "payee_name": name,
                "amount_inr": amount, "can_pay": False,
                "speech": f"QR claims payee {name}, address {pa}. " + (f"Amount {amount} rupees. " if amount else "No fixed amount. ") +
                          "The owner and authenticity are NOT verified. Confirm independently. No payment has been made."}
    if not shutil.which("tesseract"):
        return {"mode": "CURRENCY", "status": "OCR_UNAVAILABLE", "speech": "No UPI QR found. Currency OCR is unavailable on this server.", "can_pay": False}
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot prepare currency image")
    process = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "-l", "eng"],
                             input=png.tobytes(), capture_output=True, timeout=5, check=False)
    text = process.stdout.decode("utf-8", errors="replace")[:10000].upper()
    denominations = sorted({int(number) for number in re.findall(r"\b(?:10|20|50|100|200|500|2000)\b", text)})
    bank_words = any(word in text for word in ("RESERVE", "RUPEES", "RUPEE", "BHARATIYA", "BANK"))
    if denominations and bank_words:
        speech = "Possible denomination text: " + ", ".join(f"{d} rupees" for d in denominations) + ". This is OCR only, not note authentication."
        if 2000 in denominations:
            speech += " The 2000 rupee note was withdrawn from circulation; check current RBI guidance."
        return {"mode": "CURRENCY", "status": "OCR_CANDIDATE", "denominations": denominations, "speech": speech, "can_pay": False}
    return {"mode": "CURRENCY", "status": "INCONCLUSIVE", "speech": "No reliable denomination text or UPI QR was found. Improve lighting and show one item at a time.", "can_pay": False}
