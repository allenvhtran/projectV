"""Zero-cost stand-ins for the two stages that spend money.

The point is rhythm. Before you buy 8,500 characters of narration and 35
images, you want to know whether 35 beats over ten minutes actually breathes
or whether the cuts land like a metronome -- and that is a question about
timing, which needs no real audio and no real images to answer.

Narration is replaced by silence of the length the words would take at the
configured rate. Stills are replaced by cards carrying the beat number, the
section, and the image prompt, so you can read what each shot was meant to be
while you watch the pacing.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from .media import silence

# Section -> background, so the structure of the episode is visible as colour
# blocks while it plays.
SECTION_COLORS = {
    "cold_open": (26, 18, 22),
    "setup": (18, 22, 28),
    "escalation": (24, 20, 16),
    "turn": (34, 18, 18),
    "aftermath": (16, 22, 22),
    "resolution": (20, 18, 28),
    "outro": (14, 14, 16),
}
FALLBACK = (20, 20, 24)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def estimate_seconds(text: str, wpm: int) -> float:
    """What the narration will take once it's real. Deliberately the same
    figure the script stage targets, so a dry run and the real thing land at
    the same runtime."""
    return max(1.0, len(text.split()) / wpm * 60)


def fake_narration(text: str, wpm: int, out: Path) -> float:
    seconds = estimate_seconds(text, wpm)
    silence(out, seconds)
    return seconds


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def placeholder_card(beat: dict, out: Path, size: str = "1344x768") -> None:
    """A readable card standing in for a generated still. Falls back to a flat
    colour field if Pillow isn't installed -- the pacing still reads."""
    w, h = (int(x) for x in size.split("x"))
    bg = SECTION_COLORS.get(beat.get("section", ""), FALLBACK)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        from .media import run as ff

        ff(["ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=rgb({bg[0]}\\,{bg[1]}\\,{bg[2]}):s={w}x{h}:d=1",
            "-frames:v", "1", str(out)])
        return

    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    # Vertical gradient, so the Ken Burns move is visible on the card.
    for y in range(h):
        k = 1.0 - (y / h) * 0.55
        d.line([(0, y), (w, y)], fill=tuple(int(c * k) for c in bg))

    hero = beat.get("hero")
    d.text((70, 60), f"BEAT {beat['id']:03d}", font=_font(52),
           fill=(210, 200, 190) if hero else (140, 140, 150))
    d.text((70, 124), beat.get("section", "").replace("_", " ").upper()
           + ("   ·   HERO" if hero else ""),
           font=_font(26), fill=(120, 130, 140))

    d.text((70, 210), "\n".join(textwrap.wrap(beat.get("image_prompt", ""), 52)),
           font=_font(30), fill=(190, 190, 195), spacing=12)

    narration = beat.get("narration", "")
    preview = narration[:150] + ("…" if len(narration) > 150 else "")
    d.text((70, h - 190), "\n".join(textwrap.wrap(preview, 74)),
           font=_font(22), fill=(105, 110, 120), spacing=8)

    d.rectangle([(0, h - 10), (w, h)], fill=(60, 50, 45) if hero else (40, 42, 48))
    img.save(out)
