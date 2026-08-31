"""Orchestrator.

  python -m pipeline.cli new                     # full run, stops before upload
  python -m pipeline.cli run --slug ep001-...    # resume an episode
  python -m pipeline.cli run --stage assemble    # re-run one stage on the latest
  python -m pipeline.cli upload --publish        # ship it
  python -m pipeline.cli voices                  # list ElevenLabs voices
  python -m pipeline.cli costs                   # month-to-date spend
  python -m pipeline.cli calibrate               # measure your real words/min
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from importlib import import_module

from .config import Config
from .costs import check_ceilings, month_total
from .state import Manifest
from .variation import choose

# Imported lazily: each stage pulls in its own vendor SDK, and `costs`,
# `seed` and `calibrate` need none of them. Eager imports meant a missing
# optional dependency broke every subcommand, not just the one using it.
STAGE_MODULES = {
    "script": "s1_script",
    "voice": "s2_voice",
    "visuals": "s3_visuals",
    "music": "s4_music",
    "assemble": "s5_assemble",
    "metadata": "s6_metadata",
}
ORDER = list(STAGE_MODULES)


DRY_CAPABLE = {"voice", "visuals"}      # take dry_run=
PREVIEW_CAPABLE = {"assemble"}          # take preview=


def stage_fn(name: str):
    try:
        return import_module(f".stages.{STAGE_MODULES[name]}", __package__).run
    except ImportError as exc:
        raise SystemExit(
            f"Stage '{name}' needs a dependency that isn't installed ({exc}).\n"
            f"Run: pip install -r requirements.txt"
        ) from exc


def cmd_new(args) -> None:
    cfg = Config.load()
    var = choose(cfg.pipeline, seed=args.seed)
    print(
        f"Episode plan: {var['structure']} / {var['cold_open']} / "
        f"{var['resolution']}\n  setting: {var['setting']}\n"
        f"  target:  {var['runtime_minutes']} min"
    )
    m = Manifest.create(var["setting"], variation=var)
    print(f"  slug:    {m.slug}\n")
    _run_stages(m, cfg, ORDER, args.force, dry_run=getattr(args, "dry_run", False))


def cmd_run(args) -> None:
    cfg = Config.load()
    m = Manifest.load(args.slug) if args.slug else Manifest.latest()
    print(f"Episode {m.slug}\n")
    stages = [args.stage] if args.stage else ORDER
    _run_stages(m, cfg, stages, args.force, dry_run=args.dry_run,
                preview=getattr(args, "preview", False))


def _run_stages(m: Manifest, cfg: Config, stages: list[str], force: bool,
                dry_run: bool = False, preview: bool = False) -> None:
    if dry_run:
        # The paid stages get stand-ins; metadata is simply skipped, since its
        # only output is packaging you would rewrite before publishing anyway.
        stages = [s for s in stages if s != "metadata"]
        m.data["dry_run"] = True
        m.save()

    for name in stages:
        print(f"[{name}]")
        fn = stage_fn(name)
        if dry_run and name in DRY_CAPABLE:
            m = fn(m, cfg, force=force, dry_run=True)
        elif name in PREVIEW_CAPABLE and (dry_run or preview):
            m = fn(m, cfg, force=force, preview=True)
        else:
            m = fn(m, cfg, force=force)
        check_ceilings(m, cfg.pipeline)

    total = m.data.get("costs", {}).get("total", 0.0)
    if dry_run:
        print(
            f"\nDRY RUN complete: {m.dir}\n"
            f"Spent: $0.00. Watch {m.data.get('video', {}).get('path', 'the render')} "
            f"for pacing, then re-run for real:\n"
            f"  python -m pipeline.cli run --slug {m.slug} --force"
        )
        return
    print(
        f"\nDone: {m.dir}\n"
        f"Episode cost: ${total:.2f}   Month to date: ${month_total(m.data['created_at'][:7]):.2f}\n"
        f"Review the render, then: python -m pipeline.cli upload --slug {m.slug}"
    )


def cmd_seed(args) -> None:
    """Import a hand-written script from seed/ as a new episode, skipping the
    script stage. This is how a script you wrote yourself (or heavily edited)
    enters the pipeline -- everything downstream is identical."""
    from .config import ROOT

    path = ROOT / "seed" / args.file
    if not path.exists():
        matches = sorted((ROOT / "seed").glob(f"*{args.file}*"))
        if not matches:
            raise SystemExit(f"No seed script matching {args.file} in seed/")
        path = matches[0]

    cfg = Config.load()
    with open(path) as fh:
        script = json.load(fh)
    var = script.pop("_variation", None) or choose(cfg.pipeline)
    hint = script.pop("_slug_hint", None) or var["setting"]

    m = Manifest.create(hint, variation=var)
    beats = script["beats"]
    words = sum(len(b["narration"].split()) for b in beats)
    m.data["script"] = script
    m.data["title"] = script.get("title", "")
    m.data["script_stats"] = {
        "beats": len(beats), "words": words,
        "chars": sum(len(b["narration"]) for b in beats),
        "est_runtime_min": round(words / cfg.pipeline["target"]["words_per_minute"], 2),
        "hero_beats": sum(1 for b in beats if b.get("hero")),
    }
    m.path("meta", "script.txt").write_text(
        "\n\n".join(b["narration"] for b in beats)
    )
    m.mark("script", model="hand-written", source=path.name, **m.data["script_stats"])
    print(f"Seeded {m.slug} from {path.name}: {len(beats)} beats, {words} words")
    print(f"Next: python -m pipeline.cli run --slug {m.slug}")


def cmd_upload(args) -> None:
    from .stages import s7_upload

    cfg = Config.load()
    m = Manifest.load(args.slug) if args.slug else Manifest.latest()
    s7_upload.run(m, cfg, force=args.force, publish=args.publish,
                  publish_at=args.publish_at)


def cmd_voices(args) -> None:
    from .stages.s2_voice import list_voices

    for v in list_voices():
        labels = v.get("labels", {}) or {}
        desc = ", ".join(f"{k}={x}" for k, x in labels.items() if x)
        print(f"{v['voice_id']}  {v['name']:<24} {desc}")


def cmd_costs(args) -> None:
    from .config import EPISODES

    rows = []
    for p in sorted(EPISODES.glob("ep*/manifest.json")):
        with open(p) as fh:
            d = json.load(fh)
        rows.append((d.get("created_at", "")[:10], d["slug"],
                     d.get("costs", {}).get("total", 0.0),
                     d.get("narration_chars", 0), bool(d.get("dry_run"))))
    from .costs import month_chars, voice_spend

    plan = Config.load().pipeline["elevenlabs"]
    for date, slug, cost, c, dry in rows:
        tag = "  [dry run, nothing spent]" if dry else ""
        print(f"{date}  {slug:<52} ${cost:>6.2f}  {c:>7,} chars{tag}")

    this_month = time.strftime("%Y-%m")
    used = month_chars(this_month)
    allowance = plan["monthly_credits"] / plan.get("credits_per_char", 1.0)
    _, overage = voice_spend(used, plan)

    real = [r for r in rows if not r[4]]
    print(f"\n{len(real)} real episodes ({len(rows) - len(real)} dry)"
          f"   variable spend ${sum(r[2] for r in rows):.2f}"
          f"   {sum(r[3] for r in real):,} TTS chars billed")
    print(f"\n{plan['plan']} plan, {this_month}: {used:,} of {allowance:,.0f} chars "
          f"({used / allowance * 100:.0f}%)"
          + (f"   overage ${overage:.2f}" if overage else "   no overage"))
    room = (allowance - used) / 7258
    print(f"Room left this month: ~{max(0, room):.1f} more episodes at 7,258 chars each")
    print(f"\nFixed monthly: ElevenLabs ${plan['monthly_usd']:.0f} + music ~$15"
          f" (+ stock/SEO if you keep them)")


def cmd_calibrate(args) -> None:
    """Your real words-per-minute, measured from rendered episodes. Update
    config/pipeline.yaml with it -- guessing 150 when you narrate at 138 makes
    every episode a minute short of target."""
    from .config import EPISODES

    words = secs = 0
    for p in sorted(EPISODES.glob("ep*/manifest.json")):
        with open(p) as fh:
            d = json.load(fh)
        if not d.get("narration_seconds"):
            continue
        words += sum(len(b["narration"].split())
                     for b in d.get("script", {}).get("beats", []))
        secs += d["narration_seconds"]
    if not secs:
        print("No rendered narration yet.")
        return
    print(f"Measured: {words / (secs / 60):.1f} words/min across "
          f"{secs / 60:.1f} min of narration.")


def cmd_auth(args) -> None:
    from .stages import s7_upload

    s7_upload.authorize()


def main() -> None:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="start and build a new episode")
    new.add_argument("--seed", type=int, help="reproducible variation choice")
    new.add_argument("--force", action="store_true")
    new.add_argument("--dry-run", action="store_true",
                     help="stand-ins for voice and images; costs nothing")
    new.set_defaults(func=cmd_new)

    run_p = sub.add_parser("run", help="resume or re-run stages")
    run_p.add_argument("--slug")
    run_p.add_argument("--stage", choices=ORDER)
    run_p.add_argument("--force", action="store_true")
    run_p.add_argument("--dry-run", action="store_true",
                       help="stand-ins for voice and images; costs nothing")
    run_p.add_argument("--preview", action="store_true",
                       help="720p fast render of real assets, for pacing checks")
    run_p.set_defaults(func=cmd_run)

    sd = sub.add_parser("seed", help="import a hand-written script from seed/")
    sd.add_argument("file", help="filename or substring, e.g. ep001")
    sd.set_defaults(func=cmd_seed)

    up = sub.add_parser("upload")
    up.add_argument("--slug")
    up.add_argument("--publish", action="store_true", help="public instead of private")
    up.add_argument("--publish-at", help="RFC3339 scheduled publish time")
    up.add_argument("--force", action="store_true")
    up.set_defaults(func=cmd_upload)

    for name, fn in (("voices", cmd_voices), ("costs", cmd_costs),
                     ("calibrate", cmd_calibrate), ("auth", cmd_auth)):
        s = sub.add_parser(name)
        s.set_defaults(func=fn)

    args = p.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
