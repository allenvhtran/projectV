"""Config loading and episode paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
EPISODES = ROOT / "episodes"
ASSETS = ROOT / "assets"

load_dotenv(ROOT / ".env")


def _load(name: str) -> dict:
    with open(ROOT / "config" / name) as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class Config:
    channel: dict
    pipeline: dict

    @classmethod
    def load(cls) -> "Config":
        return cls(channel=_load("channel.yaml"), pipeline=_load("pipeline.yaml"))


def env(key: str, required: bool = True, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise SystemExit(
            f"Missing {key}. Copy .env.example to .env and fill it in."
        )
    return val or ""


def episode_dir(slug: str) -> Path:
    d = EPISODES / slug
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("audio", "images", "clips", "meta"):
        (d / sub).mkdir(exist_ok=True)
    return d
