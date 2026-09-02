"""Stage 1: story generation via the Claude API.

Produces a beat-structured script. One beat == one narration chunk == one
image == one shot, which is what makes audio/visual sync fall out for free
later instead of needing forced alignment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from anthropic import Anthropic

from ..config import ROOT, Config, env
from ..costs import RATES
from ..schema import Script
from ..state import Manifest


def _render_prompt(cfg: Config, var: dict) -> str:
    tmpl = (ROOT / "prompts" / "story.md").read_text()
    ch = cfg.channel["channel"]
    tgt = cfg.pipeline["target"]

    runtime = var["runtime_minutes"]
    target_words = int(runtime * tgt["words_per_minute"])
    spb_min, spb_max = tgt["seconds_per_beat_min"], tgt["seconds_per_beat_max"]
    wpm = tgt["words_per_minute"]
    beat_words_min = int(spb_min * wpm / 60)
    beat_words_max = int(spb_max * wpm / 60)
    avg_beat_words = (beat_words_min + beat_words_max) / 2
    target_beats = max(8, round(target_words / avg_beat_words))

    return tmpl.format(
        channel_name=ch["name"],
        tagline=ch["tagline"],
        narrator_persona=ch["narrator_persona"].strip(),
        structure=var["structure"],
        structure_desc=var["structure_desc"],
        cold_open=var["cold_open"],
        cold_open_desc=var["cold_open_desc"],
        resolution=var["resolution"],
        setting=var["setting"],
        runtime_minutes=runtime,
        target_words=target_words,
        target_beats=target_beats,
        beat_words_min=beat_words_min,
        beat_words_max=beat_words_max,
        seconds_per_beat_min=spb_min,
        seconds_per_beat_max=spb_max,
    )


def _extract_json(text: str) -> dict:
    """Models occasionally wrap JSON in a fence despite instructions."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def run(m: Manifest, cfg: Config, force: bool = False) -> Manifest:
    if m.done("script") and not force:
        print("  script: already done, skipping")
        return m

    client = Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    model = env("SCRIPT_MODEL", required=False, default="claude-opus-5")
    prompt = _render_prompt(cfg, m.data["variation"])

    print(f"  script: generating with {model} ...")
    # Three things this call gets right, each learned the hard way:
    #
    # No temperature -- sampling parameters are rejected with a 400 on Opus 5.
    # Creative range comes from the prompt and the per-episode variation draw.
    #
    # output_format constrains generation to the Script schema, so there is no
    # JSON to scrape out of prose and no fence to strip.
    #
    # Streaming with a large max_tokens -- thinking tokens are drawn from the
    # same budget as output, so a 35-beat script plus reasoning overruns 16k
    # and truncates mid-string. Streaming also keeps a long generation from
    # hitting the SDK's HTTP timeout.
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        output_format=Script,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        resp = stream.get_final_message()

    if resp.stop_reason == "refusal":
        raise SystemExit(
            "The model declined this prompt "
            f"({getattr(resp.stop_details, 'category', 'unknown')}). "
            "Check the setting and structure drawn for this episode."
        )
    if resp.stop_reason == "max_tokens":
        raise SystemExit(
            "Generation hit max_tokens and the script is incomplete. Raise "
            "max_tokens in s1_script.run, or lower target.runtime_minutes."
        )
    script = resp.parsed_output.model_dump()

    beats = script["beats"]
    if len(beats) < 6:
        raise SystemExit(f"Script came back with only {len(beats)} beats; aborting.")

    # The schema guarantees the fields exist; this fixes their values. Beat ids
    # are renumbered because the model occasionally restarts its own counter,
    # and pauses are clamped because an out-of-range one distorts the timeline
    # that every later stage is built on.
    default_pause = cfg.channel["voice"]["beat_pause_default"]
    for i, b in enumerate(beats, start=1):
        b["id"] = i
        pause = b.get("pause_after") or default_pause
        b["pause_after"] = min(2.5, max(0.3, float(pause)))
    beats[-1]["pause_after"] = 1.5

    words = sum(len(b["narration"].split()) for b in beats)
    chars = sum(len(b["narration"]) for b in beats)
    wpm = cfg.pipeline["target"]["words_per_minute"]

    m.data["script"] = script
    m.data["script_stats"] = {
        "beats": len(beats),
        "words": words,
        "chars": chars,
        "est_runtime_min": round(words / wpm, 2),
        "hero_beats": sum(1 for b in beats if b["hero"]),
    }
    m.data.setdefault("title", script.get("title", ""))

    usd = (
        resp.usage.input_tokens / 1e6 * RATES["claude_input_per_mtok"]
        + resp.usage.output_tokens / 1e6 * RATES["claude_output_per_mtok"]
    )
    m.add_cost("script", usd)

    (m.path("meta", "script.txt")).write_text(
        "\n\n".join(b["narration"] for b in beats)
    )
    m.mark("script", model=model, **m.data["script_stats"])
    print(
        f"  script: {len(beats)} beats, {words} words, "
        f"~{words / wpm:.1f} min, ${usd:.3f}"
    )
    return m
