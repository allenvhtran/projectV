"""Episode manifest: the single source of truth, and what makes stages resumable.

Every stage reads the manifest, does its work, and writes back. Re-running a
stage whose outputs already exist is a no-op unless --force is passed, so a
failure at assembly never costs you another round of TTS or image spend.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import EPISODES, episode_dir

MANIFEST = "manifest.json"


def slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen].strip("-")


def next_episode_number() -> int:
    nums = []
    for p in EPISODES.glob("ep*"):
        m = re.match(r"ep(\d+)", p.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


class Manifest:
    def __init__(self, slug: str, data: dict[str, Any]):
        self.slug = slug
        self.data = data
        self.dir = episode_dir(slug)

    @classmethod
    def create(cls, title_hint: str, **fields) -> "Manifest":
        n = next_episode_number()
        slug = f"ep{n:03d}-{slugify(title_hint)}"
        data = {
            "slug": slug,
            "number": n,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stages": {},
            "costs": {},
            **fields,
        }
        m = cls(slug, data)
        m.save()
        return m

    @classmethod
    def load(cls, slug: str) -> "Manifest":
        path = EPISODES / slug / MANIFEST
        if not path.exists():
            raise SystemExit(f"No manifest at {path}")
        with open(path) as fh:
            return cls(slug, json.load(fh))

    @classmethod
    def latest(cls) -> "Manifest":
        dirs = sorted(p for p in EPISODES.glob("ep*") if (p / MANIFEST).exists())
        if not dirs:
            raise SystemExit("No episodes yet. Run: python -m pipeline.cli new")
        return cls.load(dirs[-1].name)

    def save(self) -> None:
        with open(self.dir / MANIFEST, "w") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)

    # -- stage bookkeeping ---------------------------------------------------
    def done(self, stage: str) -> bool:
        return bool(self.data.get("stages", {}).get(stage, {}).get("ok"))

    def mark(self, stage: str, **info) -> None:
        self.data.setdefault("stages", {})[stage] = {
            "ok": True,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **info,
        }
        self.save()

    def add_cost(self, key: str, usd: float) -> None:
        costs = self.data.setdefault("costs", {})
        costs[key] = round(costs.get(key, 0.0) + usd, 4)
        costs["total"] = round(
            sum(v for k, v in costs.items() if k != "total"), 4
        )
        self.save()

    @property
    def beats(self) -> list[dict]:
        return self.data.get("script", {}).get("beats", [])

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)
