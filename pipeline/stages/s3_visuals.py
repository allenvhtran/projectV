"""Stage 3: one still per beat, via Replicate (FLUX).

Cost control: hero beats (the cold open, the turn, the last shot) render on
flux-dev; everything else on flux-schnell, which is ~8x cheaper and perfectly
adequate for a shot that is on screen for 14 seconds under a Ken Burns move
and a grain overlay.

Note on Midjourney: it has no official API and its ToS forbids automated
access, so it is not wired in here. See docs/STACK.md.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import Config, env
from ..costs import RATES
from ..dryrun import placeholder_card
from ..state import Manifest

API = "https://api.replicate.com/v1"


class Fatal(Exception):
    """An error that retrying cannot fix: bad credentials, a blocked network,
    a malformed request. Retrying these 3 times per beat across 35 beats turns
    one misconfiguration into minutes of exponential backoff before the run
    dies anyway."""


def _predict(model: str, payload: dict, token: str, timeout: int = 300) -> str:
    """Create a prediction and block until it returns an image URL."""
    try:
        r = requests.post(
            f"{API}/models/{model}/predictions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "wait",
            },
            json={"input": payload},
            timeout=timeout,
        )
    except (requests.exceptions.ProxyError,
            requests.exceptions.SSLError) as exc:
        raise Fatal(
            f"cannot reach api.replicate.com ({type(exc).__name__}). Something "
            f"between you and Replicate is refusing the connection -- proxy, "
            f"VPN, or egress filter."
        ) from exc

    if r.status_code in (401, 403):
        raise Fatal(
            f"Replicate rejected the token ({r.status_code}). Check "
            f"REPLICATE_API_TOKEN, and that billing is enabled on the account."
        )
    if r.status_code == 422:
        raise Fatal(f"Replicate rejected the request body: {r.text[:300]}")
    r.raise_for_status()
    pred = r.json()

    deadline = time.time() + timeout
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() > deadline:
            raise TimeoutError(f"Replicate prediction {pred.get('id')} timed out")
        time.sleep(2)
        pr = requests.get(
            f"{API}/predictions/{pred['id']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        pr.raise_for_status()
        pred = pr.json()

    if pred["status"] != "succeeded":
        raise RuntimeError(f"Replicate: {pred.get('error') or pred['status']}")

    out = pred["output"]
    return out[0] if isinstance(out, list) else out


def run(m: Manifest, cfg: Config, force: bool = False,
        dry_run: bool = False) -> Manifest:
    if m.done("visuals") and not force:
        print("  visuals: already done, skipping")
        return m

    vis = cfg.channel["visual"]
    if dry_run:
        made = 0
        for b in m.beats:
            dest = m.path("images", f"beat_{b['id']:03d}.png")
            if dest.exists() and not force:
                continue
            placeholder_card(b, dest, vis["gen_size"])
            made += 1
        m.mark("visuals", images=len(m.beats), rendered_now=made, dry_run=True)
        print(f"  visuals: {len(m.beats)} placeholder cards "
              f"(DRY RUN -- no images generated, $0 spent)")
        return m

    token = env("REPLICATE_API_TOKEN")
    icfg = cfg.pipeline["images"]
    beats = m.beats
    img_dir = m.path("images")

    spend = 0.0
    rendered = 0

    for b in beats:
        dest = img_dir / f"beat_{b['id']:03d}.png"
        if dest.exists() and not force:
            continue

        hero = bool(b.get("hero"))
        model = icfg["model_hero"] if hero else icfg["model_cheap"]
        prompt = f"{b['image_prompt']}. {vis['style_suffix'].strip()}"

        # FLUX on Replicate is driven by aspect_ratio + megapixels. Passing
        # width/height instead is silently unhelpful: they are not part of this
        # interface, so the model falls back to its 1:1 default and every shot
        # comes out square -- wrong for a 16:9 video, and paid for.
        payload = {
            "prompt": prompt,
            "aspect_ratio": vis.get("gen_aspect", "16:9"),
            "megapixels": str(vis.get("gen_megapixels", "1")),
            "num_outputs": 1,
            "output_format": "png",
            "disable_safety_checker": False,
        }
        if hero:
            # flux-dev: guidance 0-10 (3 is the sane default), steps 1-50 with
            # 28+ recommended for quality. No go_fast on dev.
            payload["guidance"] = 3.0
            payload["num_inference_steps"] = 28
        else:
            # flux-schnell is distilled to 4 steps; more is wasted money.
            payload["go_fast"] = True
            payload["num_inference_steps"] = 4

        url = None
        for attempt in range(icfg["retries"]):
            try:
                print(
                    f"  visuals: beat {b['id']}/{len(beats)} "
                    f"({'hero' if hero else 'std'}) ...",
                    end="\r", flush=True,
                )
                url = _predict(model, payload, token)
                break
            except Fatal as exc:
                # No amount of waiting fixes these. Stop on the first one so
                # the message is visible instead of buried under 34 more.
                raise SystemExit(f"\n  visuals: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - transient; worth a retry
                if attempt == icfg["retries"] - 1:
                    raise SystemExit(
                        f"\n  visuals: beat {b['id']} failed after "
                        f"{icfg['retries']} attempts: {exc}"
                    )
                time.sleep(2 ** attempt)

        img = requests.get(url, timeout=120)
        img.raise_for_status()
        dest.write_bytes(img.content)

        b["image_model"] = model
        spend += RATES["flux_dev_per_image"] if hero else RATES["flux_schnell_per_image"]
        rendered += 1

    if spend:
        m.add_cost("images", spend)
    m.save()
    m.mark("visuals", images=len(beats), rendered_now=rendered, usd=round(spend, 4))
    print(f"  visuals: {len(beats)} stills ({rendered} new), ${spend:.3f}")
    return m
