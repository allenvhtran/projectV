"""Stage 4: pick a music bed.

Deliberately a local-library picker, not an API. Licensed drone/ambient tracks
from a subscription (Artlist, Epidemic, Storyblocks) live in assets/music/ and
get rotated so consecutive episodes don't share a bed. Generative music APIs
are avoided here: the licensing position for monetised YouTube is murkier than
a flat-rate library, and a horror bed is one of the few assets where reuse
across episodes is an asset rather than a liability.

Drop .mp3/.wav files in assets/music/ and optionally annotate them in
assets/music/index.yaml:

  tracks:
    - file: slow_drone_a.mp3
      mood: [dread, sparse]
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import yaml

from ..config import ASSETS, EPISODES, Config
from ..state import Manifest

MUSIC = ASSETS / "music"
EXTS = {".mp3", ".wav", ".flac", ".m4a"}


def _available() -> list[Path]:
    return sorted(p for p in MUSIC.iterdir() if p.suffix.lower() in EXTS)


def _recent_beds(lookback: int = 6) -> list[str]:
    used = []
    dirs = sorted(p for p in EPISODES.glob("ep*") if (p / "manifest.json").exists())
    for p in dirs[-lookback:]:
        try:
            with open(p / "manifest.json") as fh:
                used.append(json.load(fh).get("music", {}).get("file"))
        except (OSError, json.JSONDecodeError):
            continue
    return [u for u in used if u]


def run(m: Manifest, cfg: Config, force: bool = False) -> Manifest:
    if m.done("music") and not force:
        print("  music: already done, skipping")
        return m

    tracks = _available()
    if not tracks:
        print(
            "  music: assets/music/ is empty -- rendering without a bed.\n"
            "         Add licensed ambient tracks there and re-run "
            "`--stage music assemble`."
        )
        m.data["music"] = None
        m.mark("music", file=None, note="no tracks available")
        return m

    recent = _recent_beds()
    fresh = [t for t in tracks if t.name not in recent] or tracks
    chosen = random.Random(m.data.get("variation", {}).get("seed")).choice(fresh)

    m.data["music"] = {
        "file": chosen.name,
        "path": str(chosen.relative_to(ASSETS.parent)),
        "volume": cfg.channel["music"]["bed_volume"],
    }
    m.mark("music", file=chosen.name)
    print(f"  music: {chosen.name}")
    return m
