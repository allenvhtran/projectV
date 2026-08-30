"""ffmpeg/ffprobe wrappers.

Resolution order: PATH, then imageio-ffmpeg's bundled static build. ffprobe is
preferred for durations but we fall back to parsing ffmpeg's own stderr so the
pipeline still runs on boxes that ship ffmpeg without ffprobe.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def _bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    raise SystemExit(
        f"{name} not found. Install ffmpeg (brew install ffmpeg / "
        f"apt-get install ffmpeg) or `pip install imageio-ffmpeg`."
    )


def run(args: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    cmd = [_bin(args[0])] + [str(a) for a in args[1:]]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"{args[0]} failed ({proc.returncode}):\n{tail}")
    return proc


def duration(path: Path | str) -> float:
    """Seconds, as a float."""
    path = str(path)
    if shutil.which("ffprobe"):
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            try:
                return float(json.loads(proc.stdout)["format"]["duration"])
            except (KeyError, ValueError, json.JSONDecodeError):
                pass
    # Fallback: ffmpeg's own header. Parse the container `Duration:` line, NOT
    # the trailing `time=` progress line -- with mismatched stream lengths that
    # progress figure tracks the *shortest* stream and silently under-reports.
    proc = subprocess.run(
        [_bin("ffmpeg"), "-i", path, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    head = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
    if head:
        h, mnt, sec = head.groups()
        return int(h) * 3600 + int(mnt) * 60 + float(sec)
    times = re.findall(r"time=(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
    if not times:
        raise RuntimeError(f"Could not determine duration of {path}")
    h, mnt, sec = times[-1]
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def silence(path: Path, seconds: float, sample_rate: int = 44100) -> Path:
    run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono",
        "-t", f"{seconds:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(path),
    ])
    return path


def concat_audio(parts: list[Path], out: Path, workdir: Path) -> Path:
    """Concat demuxer. Requires uniform codec/sample-rate across parts."""
    listfile = workdir / "concat_audio.txt"
    listfile.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in parts) + "\n"
    )
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100", "-ac", "1", str(out),
    ])
    return out
