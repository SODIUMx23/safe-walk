"""Validate and normalize independently playable browser-recorded video segments."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path


def normalize_blackbox(segments: list[bytes], duration_hints: list[float]) -> tuple[bytes, dict]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required to archive browser video")
    if not 1 <= len(segments) <= 8:
        raise ValueError("One to eight independently playable video segments are required")
    with tempfile.TemporaryDirectory(prefix="safewalk-media-") as directory:
        root = Path(directory)
        names, durations = [], []
        for index, content in enumerate(segments):
            if not content:
                continue
            name = f"segment-{index}.media"
            path = root / name
            path.write_bytes(content)
            try:
                probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                        "stream=codec_name,width,height:format=duration", "-of", "json", str(path)],
                                       capture_output=True, timeout=5, check=True)
                info = json.loads(probe.stdout)
                stream = info.get("streams", [])[0]
                if stream["width"] * stream["height"] > 1920 * 1080:
                    raise ValueError("Video resolution exceeds 1080p")
                if stream.get("codec_name") not in {"vp8", "vp9", "h264", "hevc", "av1"}:
                    raise ValueError("Unsupported browser video codec")
                duration = float(info.get("format", {}).get("duration", "nan"))
                if not math.isfinite(duration):
                    duration = duration_hints[index] / 1000 if index < len(duration_hints) else 2.0
                if not 0 < duration <= 12:
                    raise ValueError("Invalid segment duration")
                durations.append(duration)
            except (subprocess.SubprocessError, KeyError, IndexError, json.JSONDecodeError) as exc:
                raise ValueError("A video segment could not be validated") from exc
            names.append(name)
        if not names or sum(durations) > 24:
            raise ValueError("Invalid or excessive rolling buffer duration")
        (root / "segments.txt").write_text("\n".join(f"file '{name}'" for name in names), encoding="utf-8")
        output = root / "incident.mp4"
        start = max(0.0, sum(durations) - 10.0)
        command = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-f", "concat", "-safe", "1",
                   "-i", str(root / "segments.txt"), "-ss", f"{start:.3f}", "-t", "10", "-an",
                   "-vf", "fps=12,scale=640:-2,setsar=1", "-c:v", "libx264", "-threads", "1",
                   "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(output)]
        try:
            subprocess.run(command, capture_output=True, timeout=35, check=True)
        except subprocess.SubprocessError as exc:
            raise ValueError("The rolling buffer could not be normalized") from exc
        result = output.read_bytes()
        if not result or len(result) > 18 * 1024 * 1024:
            raise ValueError("Normalized archive size is invalid")
        return result, {"duration_target_s": min(10, round(sum(durations), 2)), "segments": len(names),
                        "capture_gaps_possible": True, "audio_included": False,
                        "buffer_design": "RAM ring of independently finalized 2-second segments"}
