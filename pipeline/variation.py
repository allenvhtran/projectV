"""Picks a per-episode structure that hasn't been used recently.

This is the part that keeps a daily automated channel from producing 30 videos
with the same skeleton. It is not decoration -- see docs/ORIGINALITY.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .config import EPISODES


def _recent(field: str, lookback: int) -> list[str]:
    used = []
    dirs = sorted(p for p in EPISODES.glob("ep*") if (p / "manifest.json").exists())
    for p in dirs[-lookback:]:
        try:
            with open(p / "manifest.json") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        val = data.get("variation", {}).get(field)
        if val:
            used.append(val)
    return used


def _pick(options: list, field: str, lookback: int, rng: random.Random):
    ids = [o["id"] if isinstance(o, dict) else o for o in options]
    used = _recent(field, lookback)
    fresh = [i for i in ids if i not in used]
    # If everything has been used inside the window, fall back to the
    # least-recently-used rather than repeating the newest.
    if not fresh:
        fresh = sorted(ids, key=lambda i: used[::-1].index(i) if i in used else 99)
        fresh = fresh[:1]
    return rng.choice(fresh)


def choose(cfg: dict, seed: int | None = None) -> dict:
    v = cfg["variation"]
    rng = random.Random(seed)
    lookback = v["lookback_episodes"]

    structure = _pick(v["structures"], "structure", lookback, rng)
    cold_open = _pick(v["cold_opens"], "cold_open", lookback, rng)
    resolution = _pick(v["resolutions"], "resolution", lookback, rng)
    setting = _pick(cfg["setting_pool"], "setting", lookback, rng)

    lo, hi = v["runtime_jitter_minutes"]
    runtime = round(cfg["target"]["runtime_minutes"] + rng.uniform(lo, hi), 2)

    descs = {s["id"]: s["desc"] for s in v["structures"]}
    opens = {c["id"]: c["desc"] for c in v["cold_opens"]}

    return {
        "structure": structure,
        "structure_desc": descs[structure],
        "cold_open": cold_open,
        "cold_open_desc": opens[cold_open],
        "resolution": resolution,
        "setting": setting,
        "runtime_minutes": max(6.0, runtime),
        "seed": seed,
    }
