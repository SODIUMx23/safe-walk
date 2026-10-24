"""RAM-cacheable primitives with honest synthesis provenance.

The enrollment vector is a reproducible spectral reference fingerprint, NOT an
XTTS-v2 embedding and NOT voice cloning. XTTS's commonly distributed weights
are not OSI open-source. Real loved-one playback is supported by a consented
40-recording ZIP; otherwise open-source eSpeak or browser TTS is used.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import threading
import wave
import zipfile
from pathlib import Path
from uuid import uuid4

import numpy as np

PRIMITIVES = dict([
    ("halt_void", "Papa, halt! Possible open void ahead. Check with your cane."),
    ("headspace", "Papa, stop. Possible head-height hazard ahead."),
    ("duck", "Papa, duck!"),
    ("step_right", "Papa, step right only after checking the path."),
    ("step_left", "Papa, step left only after checking the path."),
    ("halt", "Papa, halt. Please check the path."),
    ("caution", "Papa, take care. An obstacle may be ahead."),
    ("left_10", "Papa, possible obstacle at ten o'clock."),
    ("left_11", "Papa, possible obstacle at eleven o'clock."),
    ("ahead_12", "Papa, possible obstacle at twelve o'clock."),
    ("right_1", "Papa, possible obstacle at one o'clock."),
    ("right_2", "Papa, possible obstacle at two o'clock."),
    ("slow", "Papa, slow down and check with your cane."),
    ("uneven_ground", "Papa, possible uneven ground. Stop and check."),
    ("stairs_down", "Papa, possible descending steps. Stop and check."),
    ("stairs_up", "Papa, possible steps up. Stop and check."),
    ("low_light", "Papa, the camera view is too dark to assess."),
    ("camera_lost", "Papa, the camera is unavailable. Guidance is limited."),
    ("offline", "Papa, the server is offline. Cloud guidance is unavailable."),
    ("gps_lost", "Papa, GPS is unavailable. Civic hazard warnings are limited."),
    ("gps_weak", "Papa, GPS accuracy is poor. Distances may be wrong."),
    ("mesh_warning", "Papa, an unverified civic hazard is reported nearby. Stop and check."),
    ("sos_sent", "Papa, the alert reached the caregiver hub. Emergency services have not been called."),
    ("sos_failed", "Papa, the alert could not be delivered. Call your caregiver or one one two."),
    ("impact", "Papa, a strong phone impact was detected. Are you safe?"),
    ("rupee_on", "Rupee Guard on. Show one note or payment QR. Authenticity cannot be guaranteed."),
    ("rupee_off", "Rupee Guard off."),
    ("qr_unverified", "Payment details are unverified. Confirm the payee independently. No payment has been made."),
    ("currency_unknown", "The note denomination is uncertain. Please ask a trusted person."),
    ("calibrated", "Neutral head position saved. Camera geometry is still approximate."),
    ("started", "SafeWalk started. Keep using your cane or guide. Hazard detection is experimental."),
    ("stopped", "SafeWalk monitoring stopped."),
    ("no_instruction", "No recent guidance is available. This does not mean the path is clear."),
    ("scene_unavailable", "A scene description is unavailable. Please check your connection and camera."),
    ("crossing_candidate", "Possible crossing markings ahead. Do not cross based on this app."),
    ("hold_one", "Keep holding for emergency alert."),
    ("hold_two", "Emergency alert activated."),
    ("background", "Monitoring was interrupted while the app was in the background."),
    ("mount_check", "Please check the phone mount and camera direction."),
    ("audio_test", "Audio check. This is the center channel. Keep environmental sounds audible."),
])
assert len(PRIMITIVES) == 40
TEXT_TO_TOKEN = {text: key for key, text in PRIMITIVES.items()}


class VoiceService:
    def __init__(self, settings, repo):
        self.settings, self.repo = settings, repo
        self.root = settings.data_dir / "voices"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.espeak = shutil.which("espeak-ng") or shutil.which("espeak")

    def ensure_default(self):
        if not self.espeak:
            return
        with self.lock:
            directory = self.root / "default"
            directory.mkdir(exist_ok=True)
            for key, text in PRIMITIVES.items():
                path = directory / f"{key}.wav"
                if path.is_file():
                    continue
                temporary = directory / f"{key}.{uuid4().hex}.pending.wav"
                subprocess.run([self.espeak, "-v", "en-us+f3", "-s", "165", "-p", "55", "-w", str(temporary), text],
                               capture_output=True, timeout=8, check=True)
                temporary.replace(path)

    def pack(self, profile_id="default"):
        if profile_id == "default":
            profile = {"id": "default", "kind": "SYSTEM_ESPEAK_NOT_CLONED"}
        else:
            profile = self.repo.get_document("voices", profile_id)
            if not profile:
                raise ValueError("Unknown voice profile")
        recorded = profile.get("kind") == "CONSENTED_RECORDINGS"
        if not recorded:
            self.ensure_default()
        directory_id = profile_id if recorded else "default"
        entries = {}
        for key, text in PRIMITIVES.items():
            available = (self.root / directory_id / f"{key}.wav").is_file()
            entries[key] = {"text": text, "audio_url": f"/api/v1/kinvoice/primitives/{directory_id}/{key}.wav" if available else None,
                            "voice_kind": "CONSENTED_RECORDING" if recorded else "SYSTEM_ESPEAK_NOT_CLONED" if available else "BROWSER_TTS_NOT_CLONED"}
        return {"profile_id": profile_id, "kind": profile["kind"], "tokens": entries,
                "cache_target": "decoded AudioBuffer objects in local RAM", "latency_guaranteed": False,
                "latency_note": "Scheduling is measured on-device; operating systems and audio hardware can exceed 40 ms.",
                "is_voice_clone": False}

    def audio_path(self, profile_id, token):
        if token not in PRIMITIVES or (profile_id != "default" and not self.repo.get_document("voices", profile_id)):
            return None
        # IDs are looked up before any filesystem access.
        path = self.root / profile_id / f"{token}.wav"
        return path if path.is_file() else None

    @staticmethod
    def _pcm(audio: bytes, max_seconds=13):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required to validate uploaded audio")
        try:
            process = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0",
                                      "-t", str(max_seconds), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                                     input=audio, capture_output=True, timeout=15, check=True)
        except subprocess.SubprocessError as exc:
            raise ValueError("The audio sample could not be decoded") from exc
        return np.frombuffer(process.stdout, dtype="<i2").astype(np.float32) / 32768.0

    def enroll(self, audio: bytes):
        samples = self._pcm(audio)
        duration = len(samples) / 16000
        if not 8 <= duration <= 12:
            raise ValueError("Please provide a 10-second audio sample (accepted duration: 8–12 seconds)")
        if float(np.sqrt(np.mean(samples ** 2))) < .002:
            raise ValueError("The audio sample is too quiet or silent")
        spectrum = np.abs(np.fft.rfft(samples[:16000 * 8]))
        bins = np.array([np.log1p(np.mean(part)) for part in np.array_split(spectrum, 32)])
        norm = float(np.linalg.norm(bins)) or 1.0
        profile_id = str(uuid4())
        profile = {"id": profile_id, "kind": "REFERENCE_ONLY_SIMULATED_EMBEDDING_NOT_CLONING",
                   "embedding_type": "32-bin spectral reference fingerprint, not XTTS-v2",
                   "simulated_embedding": [round(float(v / norm), 6) for v in bins],
                   "sample_duration_s": round(duration, 2), "sample_sha256": hashlib.sha256(audio).hexdigest(),
                   "raw_sample_retained": False, "consent_recorded": True}
        self.repo.save_document("voices", profile_id, profile)
        return {**profile, **self.pack(profile_id)}

    def install_recordings(self, profile_id, archive: bytes):
        if profile_id == "default" or not self.repo.get_document("voices", profile_id):
            raise ValueError("Enroll a reference sample before uploading its consented recording pack")
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            files = [info for info in zip_file.infolist() if not info.is_dir()]
            if len(files) != 40 or sum(info.file_size for info in files) > 40 * 1024 * 1024:
                raise ValueError("ZIP must contain exactly 40 audio files and at most 40 MB uncompressed")
            by_token = {}
            for info in files:
                name = Path(info.filename)
                if name.name != info.filename or name.stem not in PRIMITIVES or name.suffix.lower() not in {".wav", ".mp3", ".ogg", ".m4a", ".webm"}:
                    raise ValueError("Each recording must be a top-level audio file named after a primitive ID")
                if info.file_size > 3 * 1024 * 1024 or name.stem in by_token:
                    raise ValueError("Duplicate or oversized recording")
                by_token[name.stem] = info
            if set(by_token) != set(PRIMITIVES):
                raise ValueError("The recording pack must include every primitive ID once")
            with tempfile.TemporaryDirectory(prefix="voice-", dir=self.root) as tmp:
                temporary = Path(tmp)
                for token, info in by_token.items():
                    samples = self._pcm(zip_file.read(info), max_seconds=11)
                    if not .15 <= len(samples) / 16000 <= 10:
                        raise ValueError(f"Recording {token} must be between 0.15 and 10 seconds")
                    if float(np.sqrt(np.mean(samples ** 2))) < .002:
                        raise ValueError(f"Recording {token} is silent")
                    with wave.open(str(temporary / f"{token}.wav"), "wb") as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(16000)
                        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                destination = self.root / profile_id
                destination.mkdir(exist_ok=True)
                for path in temporary.glob("*.wav"):
                    path.replace(destination / path.name)
        profile = self.repo.get_document("voices", profile_id)
        profile["kind"] = "CONSENTED_RECORDINGS"
        self.repo.update_document("voices", profile_id, profile)
        return self.pack(profile_id)
