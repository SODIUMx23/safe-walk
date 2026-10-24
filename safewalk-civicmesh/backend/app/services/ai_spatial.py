"""Clock geometry and conservative fusion, not a metric depth/sonar estimator.

Coordinates are normalized camera pixels. `headspace_cm` is a reported lower
edge's height above the pavement; `ground_cm` is a reported DROP DEPTH relative
to pavement (not distance from a phone to the ground). Neither is fabricated
from monocular imagery. An 18-degree upward visual sector is only a candidate
filter; it cannot certify that the walking path is clear.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


HEAD_MIN_CM = 140.0
HEAD_MAX_CM = 190.0
VOID_MIN_CM = 40.0
UPWARD_CONE_DEG = 18.0


def _coordinates(box) -> tuple[float, float, float, float]:
    values = box.model_dump() if hasattr(box, "model_dump") else box
    if not isinstance(values, Mapping):
        raise ValueError("box must contain normalized x_min/y_min/x_max/y_max")
    try:
        x1, y1, x2, y2 = (float(values[k]) for k in ("x_min", "y_min", "x_max", "y_max"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid bounding box") from exc
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x1, y1, x2, y2)):
        raise ValueError("Box coordinates must be finite and normalized")
    if x1 > x2 or y1 > y2:
        raise ValueError("Inverted bounding box")
    return x1, y1, x2, y2


def calculate_clock_and_pan(box) -> tuple[str, float]:
    """Return coarse clock and continuous pan.

    x=.15 => 10 o'clock / -.7; x=.5 => 12 / 0; x=.85 => 2 / +.7.
    Extreme image edges saturate the coarse clock at 10/2 but pan reaches +/-1.
    Clock sectors are navigation cues, not surveyed compass bearings.
    """
    x1, _, x2, _ = _coordinates(box)
    pan = max(-1.0, min(1.0, x1 + x2 - 1.0))
    scaled = pan * 2.0 / 0.7
    offset = int(math.copysign(math.floor(abs(scaled) + 0.5), scaled)) if scaled else 0
    offset = max(-2, min(2, offset))
    hour = (12 + offset - 1) % 12 + 1
    return f"{hour} o'clock", round(pan, 5)


def project_angles(box, pitch: float, horizontal_fov=70.0, vertical_fov=54.0) -> dict:
    if not math.isfinite(pitch) or not -90 <= pitch <= 90:
        raise ValueError("Pitch must be finite and between -90 and 90 degrees")
    if not (0 < horizontal_fov < 180 and 0 < vertical_fov < 180):
        raise ValueError("Invalid camera field of view")
    x1, y1, x2, y2 = _coordinates(box)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    yaw = math.degrees(math.atan((2 * cx - 1) * math.tan(math.radians(horizontal_fov / 2))))
    elevation = pitch + math.degrees(math.atan((1 - 2 * cy) * math.tan(math.radians(vertical_fov / 2))))
    return {"azimuth_deg": round(yaw, 2), "elevation_deg": round(elevation, 2),
            "in_headspace_cone": 0 <= elevation <= UPWARD_CONE_DEG}


def _valid_range(value, name):
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be a nonnegative finite measurement or None")


def classify_hazard_elevation(box, pitch, headspace_cm=None, ground_cm=None) -> str:
    """Reported metric evidence takes priority over visual perspective.

    Unknown/no-echo is NOT a 40 cm drop. The caller must separately label weak
    visual ground/head candidates as unverified; a ray alone proves no height.
    """
    project_angles(box, pitch)  # validate geometry even when a range overrides it
    _valid_range(headspace_cm, "headspace_cm")
    _valid_range(ground_cm, "ground_cm")
    if ground_cm is not None and ground_cm >= VOID_MIN_CM:
        return "GROUND_VOID"
    if headspace_cm is not None and HEAD_MIN_CM <= headspace_cm <= HEAD_MAX_CM:
        return "HEAD_LEVEL"
    return "PATH_OBSTACLE"


def generate_kinvoice_speech(label, type, clock, dist=None, urgency="warning") -> str:
    """Warm wording without inventing depth, diagnosis, or a clear-path claim."""
    if type == "GROUND_VOID":
        return "Papa, halt! Possible open void ahead. Check with your cane."
    if type == "HEAD_LEVEL":
        return "Papa, stop. Possible head-height hazard ahead."
    distance = ""
    if dist is not None and math.isfinite(dist) and dist > 0:
        distance = f", about {dist:.1f} meters away (reported distance)"
    safe_label = " ".join(str(label).replace("<", "").replace(">", "").split())[:60] or "obstacle"
    prefix = "Papa, stop." if urgency == "critical" else "Papa, take care."
    return f"{prefix} Possible {safe_label} at {clock}{distance}."


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da, dl = a2 - a1, math.radians(lon2 - lon1)
    value = math.sin(da / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(max(0, min(1, value))))
