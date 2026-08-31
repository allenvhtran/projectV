"""Stage 2: narration via the ElevenLabs API.

Each beat is synthesised as its own file. That costs nothing extra (billing is
per character) and buys three things: per-beat retry without re-paying for the
whole episode, exact per-beat durations for image timing, and the ability to
re-read a single bad line without regenerating the episode.

`previous_text`/`next_text` are passed so the model keeps prosody continuous
across the chunk boundaries instead of resetting its intonation every beat.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import Config, env
from ..costs import month_chars, voice_spend
from ..dryrun import fake_narration
from ..media import concat_audio, duration, silence
from ..state import Manifest

API = "https://api.elevenlabs.io/v1"
CONTEXT_CHARS = 300


def list_voices() -> list[dict]:
    r = requests.get(
        f"{API}/voices", headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, timeout=30
    )
    r.raise_for_status()
    return r.json().get("voices", [])


def _tts(text: str, prev: str, nxt: str, voice_id: str, vcfg: dict, out: Path,
         output_format: str = "mp3_44100_128") -> None:
    body = {
        "text": text,
        "model_id": vcfg["model_id"],
        "voice_settings": {
            "stability": vcfg["stability"],
            "similarity_boost": vcfg["similarity_boost"],
            "style": vcfg["style"],
            "use_speaker_boost": True,
            "speed": vcfg["speed"],
        },
    }
    if prev:
        body["previous_text"] = prev[-CONTEXT_CHARS:]
    if nxt:
        body["next_text"] = nxt[:CONTEXT_CHARS]

    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(
                f"{API}/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": env("ELEVENLABS_API_KEY"),
                    "Content-Type": "application/json",
                },
                params={"output_format": output_format},
                json=body,
                timeout=180,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            out.write_bytes(r.content)
            return
        except Exception as exc:  # noqa: BLE001 - retry on anything transient
            last_err = exc
            time.sleep(2 ** attempt)
    raise SystemExit(f"TTS failed for {out.name} after 4 attempts: {last_err}")


def run(m: Manifest, cfg: Config, force: bool = False,
        dry_run: bool = False) -> Manifest:
    if m.done("voice") and not force:
        print("  voice: already done, skipping")
        return m

    vcfg = cfg.channel["voice"]
    plan = cfg.pipeline["elevenlabs"]
    voice_id = "DRY-RUN" if dry_run else env("ELEVENLABS_VOICE_ID")
    wpm = cfg.pipeline["target"]["words_per_minute"]

    # Warn before spending, not after. An episode that tips you into overage
    # is fine -- one that does it because you forgot you already re-read three
    # episodes this month is not.
    if not dry_run:
        pending = sum(len(b["narration"]) for b in m.beats)
        used = month_chars(m.data.get("created_at", "")[:7])
        allowance = plan["monthly_credits"] / plan.get("credits_per_char", 1.0)
        if used + pending > allowance:
            over_chars = used + pending - allowance
            cost = over_chars / 1000 * plan.get("overage_usd_per_1k", 0.30)
            print(f"  voice: NOTE this episode crosses the {plan['plan']} "
                  f"allowance ({used + pending:,.0f} of {allowance:,.0f} chars). "
                  f"Overage on it: ~${cost:.2f}")
    beats = m.beats
    audio_dir = m.path("audio")

    parts: list[Path] = []
    timeline: list[dict] = []
    cursor = 0.0
    total_chars = 0

    for i, b in enumerate(beats):
        clip = audio_dir / f"beat_{b['id']:03d}.mp3"
        if not clip.exists() or force:
            print(f"  voice: beat {b['id']}/{len(beats)} ...", end="\r", flush=True)
            if dry_run:
                fake_narration(b["narration"], wpm, clip)
            else:
                prev = beats[i - 1]["narration"] if i > 0 else ""
                nxt = beats[i + 1]["narration"] if i + 1 < len(beats) else ""
                _tts(b["narration"], prev, nxt, voice_id, vcfg, clip,
                     plan.get("output_format", "mp3_44100_128"))
        total_chars += len(b["narration"])

        speech = duration(clip)
        pause = float(b.get("pause_after", vcfg["beat_pause_default"]))
        gap = audio_dir / f"gap_{b['id']:03d}.mp3"
        if not gap.exists() or force:
            silence(gap, pause)

        parts += [clip, gap]
        timeline.append({
            "id": b["id"],
            "start": round(cursor, 3),
            "speech": round(speech, 3),
            "pause": round(pause, 3),
            # The shot stays on screen through the trailing silence.
            "shot_duration": round(speech + pause, 3),
        })
        cursor += speech + pause

    narration = concat_audio(parts, audio_dir / "narration.mp3", audio_dir)
    total = duration(narration)

    m.data["timeline"] = timeline
    m.data["narration_seconds"] = round(total, 2)
    m.data["narration_chars"] = total_chars

    # Inside the allowance the subscription is sunk, so only overage is a real
    # marginal cost. Booking a pro-rata share of the monthly fee here would
    # make a quiet month look expensive and a busy one look cheap.
    if not dry_run:
        month_total_chars = month_chars(m.data.get("created_at", "")[:7])
        _, overage_now = voice_spend(month_total_chars, plan)
        _, overage_before = voice_spend(month_total_chars - total_chars, plan)
        if overage_now > overage_before:
            m.add_cost("voice_overage", overage_now - overage_before)

    m.mark(
        "voice",
        dry_run=dry_run,
        seconds=round(total, 2),
        chars=total_chars,
        beats=len(beats),
        voice_id=voice_id,
    )
    if dry_run:
        print(f"  voice: {total / 60:.2f} min of estimated timing "
              f"(DRY RUN -- no audio generated, {total_chars:,} chars not spent)")
    else:
        allowance = plan["monthly_credits"] / plan.get("credits_per_char", 1.0)
        print(
            f"  voice: {total / 60:.2f} min, {total_chars:,} chars "
            f"({month_chars(m.data.get('created_at', '')[:7]):,} of "
            f"{allowance:,.0f} this month on {plan['plan']})"
        )
    return m
