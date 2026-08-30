"""End-to-end assembly smoke test. No API keys, no network.

Fabricates an episode with synthetic stills and synthetic narration, runs the
real assembly stage, and asserts the rendered duration matches the timeline.
This is the check that catches crossfade drift -- the failure mode where the
video finishes tens of seconds before the narration does.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import Config, EPISODES
from pipeline.media import _bin, duration, run as ff
from pipeline.stages import s5_assemble
from pipeline.state import Manifest

SLUG = "ep999-smoke-test"
BEATS = [(6.0, 0.6), (4.5, 0.5), (7.2, 1.4), (5.1, 0.6), (3.8, 1.5)]
COLORS = ["#101418", "#1a1410", "#0c1210", "#181018", "#0e0e14"]


def main() -> int:
    d = EPISODES / SLUG
    if d.exists():
        shutil.rmtree(d)

    cfg = Config.load()
    m = Manifest.create("smoke test", variation={"seed": 1, "setting": "test"})
    # Manifest.create allocates the next number; pin it so reruns are clean.
    real_slug = m.slug

    beats, timeline, cursor = [], [], 0.0
    for i, (speech, pause) in enumerate(BEATS, start=1):
        beats.append({
            "id": i, "section": "setup", "hero": False, "pause_after": pause,
            "narration": f"Beat number {i}. " + "This is placeholder narration. " * 4,
            "image_prompt": "test",
        })
        timeline.append({
            "id": i, "start": round(cursor, 3), "speech": speech,
            "pause": pause, "shot_duration": round(speech + pause, 3),
        })
        cursor += speech + pause

    m.data["script"] = {"title": "Smoke Test", "beats": beats}
    m.data["timeline"] = timeline
    m.data["music"] = None
    m.save()

    # Synthetic stills.
    for i, color in enumerate(COLORS, start=1):
        ff(["ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s=1344x768:d=1",
            "-vf", "noise=alls=20:allf=t", "-frames:v", "1",
            str(m.path("images", f"beat_{i:03d}.png"))])

    # Synthetic narration: one tone per beat, concatenated with real silences.
    parts = []
    for i, (speech, pause) in enumerate(BEATS, start=1):
        clip = m.path("audio", f"tone_{i:03d}.mp3")
        ff(["ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={200 + i * 40}:duration={speech}:sample_rate=44100",
            "-c:a", "libmp3lame", "-q:a", "2", "-ac", "1", str(clip)])
        gap = m.path("audio", f"gap_{i:03d}.mp3")
        ff(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{pause}", "-c:a", "libmp3lame", "-q:a", "2", str(gap)])
        parts += [clip, gap]

    from pipeline.media import concat_audio
    concat_audio(parts, m.path("audio", "narration.mp3"), m.path("audio"))

    xf = float(cfg.channel["render"]["crossfade_seconds"])
    expected = sum(t["shot_duration"] for t in timeline) + xf

    s5_assemble.run(m, cfg, force=True)

    out = m.path(m.data["video"]["path"])
    actual = duration(out)
    narration = duration(m.path("audio", "narration.mp3"))
    drift = actual - expected

    print("\n--- results ---")
    print(f"beats:              {len(BEATS)}")
    print(f"narration audio:    {narration:.2f}s")
    print(f"expected video:     {expected:.2f}s  (narration + {xf}s tail)")
    print(f"actual video:       {actual:.2f}s")
    print(f"drift:              {drift:+.3f}s")

    naive = sum(t["shot_duration"] for t in timeline) - (len(BEATS) - 1) * xf
    print(f"(naive clip length would have given {naive:.2f}s "
          f"-- {expected - naive:.2f}s short)")

    srt = m.path("meta", "captions.srt")
    print(f"captions:           {len(srt.read_text().strip().splitlines())} lines")

    ok = abs(drift) < 0.5 and out.stat().st_size > 10_000
    print(f"\n{'PASS' if ok else 'FAIL'}: {out.name} "
          f"({out.stat().st_size / 1e6:.2f} MB)")
    shutil.rmtree(EPISODES / real_slug, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
