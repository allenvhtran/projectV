"""Stage 6: title, description, tags, thumbnail.

Note on TubeBuddy/vidIQ: neither exposes a public write API for this, so they
stay a manual browser-side step for keyword research. This stage generates the
packaging; paste the title into vidIQ if you want a second opinion on it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from anthropic import Anthropic

from ..config import ROOT, Config, env
from ..costs import RATES
from ..schema import Metadata
from ..state import Manifest
from .s3_visuals import _predict


def _timestamps(m: Manifest) -> str:
    """Chapter markers at section boundaries. YouTube needs 00:00 first and
    at least three chapters for them to render."""
    beats = {b["id"]: b for b in m.beats}
    lines, seen = [], set()
    for t in m.data["timeline"]:
        sec = beats[t["id"]].get("section", "")
        if sec in seen or sec in ("outro",):
            continue
        seen.add(sec)
        s = int(t["start"])
        label = sec.replace("_", " ").title()
        lines.append(f"{s // 60:02d}:{s % 60:02d} {label}")
    if lines:
        lines[0] = "00:00 " + lines[0].split(" ", 1)[1]
    return "\n".join(lines)


def run(m: Manifest, cfg: Config, force: bool = False) -> Manifest:
    if m.done("metadata") and not force:
        print("  metadata: already done, skipping")
        return m

    client = Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    model = env("SCRIPT_MODEL", required=False, default="claude-opus-5")
    script = m.data["script"]

    prompt = (ROOT / "prompts" / "metadata.md").read_text().format(
        channel_name=cfg.channel["channel"]["name"],
        title=script.get("title", ""),
        logline=script.get("logline", ""),
        setting=m.data["variation"]["setting"],
        narration="\n\n".join(b["narration"] for b in m.beats),
    )

    print("  metadata: generating packaging ...")
    with client.messages.stream(
        model=model, max_tokens=32000, output_format=Metadata,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise SystemExit(f"Metadata generation stopped early: {resp.stop_reason}")
    meta = resp.parsed_output.model_dump()

    chapters = _timestamps(m)
    if chapters:
        meta["description"] = f"{meta.get('description', '').rstrip()}\n\n{chapters}"

    m.add_cost(
        "metadata",
        resp.usage.input_tokens / 1e6 * RATES["claude_input_per_mtok"]
        + resp.usage.output_tokens / 1e6 * RATES["claude_output_per_mtok"],
    )

    # Thumbnail: always a hero-quality render, it's the highest-leverage image
    # on the channel and costs 2.5 cents.
    thumb = m.path("images", "thumbnail.png")
    if (not thumb.exists() or force) and meta.get("thumbnail_prompt"):
        try:
            url = _predict(
                cfg.pipeline["images"]["model_hero"],
                {
                    "prompt": f"{meta['thumbnail_prompt']}. "
                              f"{cfg.channel['visual']['style_suffix'].strip()}",
                    "width": 1280, "height": 720, "num_outputs": 1,
                    "output_format": "png", "guidance": 3.0,
                    "num_inference_steps": 32,
                },
                env("REPLICATE_API_TOKEN"),
            )
            thumb.write_bytes(requests.get(url, timeout=120).content)
            m.add_cost("thumbnail", RATES["flux_dev_per_image"])
        except Exception as exc:  # noqa: BLE001
            print(f"  metadata: thumbnail render failed ({exc}); continuing")

    m.data["metadata"] = meta
    m.data["title"] = meta.get("title", m.data.get("title", ""))
    m.path("meta", "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )
    m.mark("metadata", title=m.data["title"], tags=len(meta.get("tags", [])))
    print(f"  metadata: \"{m.data['title']}\"")
    return m
