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
from ..state import Manifest

API = "https://api.replicate.com/v1"


def _predict(model: str, payload: dict, token: str, timeout: int = 300) -> str:
    """Create a prediction and block until it returns an image URL."""
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


def run(m: Manifest, cfg: Config, force: bool = False) -> Manifest:
    if m.done("visuals") and not force:
        print("  visuals: already done, skipping")
        return m

    token = env("REPLICATE_API_TOKEN")
    vis = cfg.channel["visual"]
    icfg = cfg.pipeline["images"]
    beats = m.beats
    img_dir = m.path("images")

    width, height = (int(x) for x in vis["gen_size"].split("x"))
    spend = 0.0
    rendered = 0

    for b in beats:
        dest = img_dir / f"beat_{b['id']:03d}.png"
        if dest.exists() and not force:
            continue

        hero = bool(b.get("hero"))
        model = icfg["model_hero"] if hero else icfg["model_cheap"]
        prompt = f"{b['image_prompt']}. {vis['style_suffix'].strip()}"

        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_outputs": 1,
            "output_format": "png",
            "disable_safety_checker": False,
        }
        if hero:
            payload["guidance"] = 3.0
            payload["num_inference_steps"] = 28
        else:
            payload["go_fast"] = True

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
            except Exception as exc:  # noqa: BLE001
                if attempt == icfg["retries"] - 1:
                    raise SystemExit(f"Image failed for beat {b['id']}: {exc}")
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
