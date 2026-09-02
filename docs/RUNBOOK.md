# Daily runbook

## The loop

```bash
make new                     # ~10-25 min wall clock, mostly ffmpeg
```

Before a script you're unsure about, check its rhythm for free first:

```bash
python -m pipeline.cli run --dry-run       # ~2 min, $0, placeholder assets
```

Nothing is spent, so it is worth doing on any script whose pacing you doubt.
Measured on 4 cores: a 35-beat / 9.8-minute episode dry-runs in 114 seconds.

Then, before anything ships:

1. **Read `episodes/<slug>/meta/script.txt`.** Edit it if it's flat. This is
   the step that keeps the channel on the right side of the policy in
   docs/ORIGINALITY.md — don't skip it because the render looks fine.
2. **Watch the render.** Listen for beats where the narration and the image
   are fighting, and for TTS mispronunciations of invented proper nouns.
3. `make upload` → private. Watch it once on YouTube's player.
4. Publish from Studio, or schedule: `python -m pipeline.cli upload --publish-at 2026-09-01T22:00:00Z`

## Fixing things without re-paying

| Problem | Fix |
|---|---|
| One line read wrong | delete that `audio/beat_NNN.mp3`, `run --stage voice` |
| One bad image | delete that `images/beat_NNN.png`, `run --stage visuals` |
| Wrong music bed | edit `music.file` in the manifest, `run --stage assemble --force` |
| Whole script is flat | `run --stage script --force` (new variation is NOT redrawn; delete the episode dir for that) |
| Title is weak | `metadata.title_alternates` in the manifest has two more |

Editing `meta/script.txt` alone does nothing — the manifest's `script.beats` is
what the stages read. Edit narration there and re-run voice.

## Before your first upload: safelist the channel

Whichever music library you use, connect your YouTube channel to it (Epidemic
and Artlist both call this "safelisting") **before** the first video goes up.
It is a one-time setting and it is what stops the library's own Content ID
from claiming your videos.

Doing it afterwards means disputing claims on everything already published --
tedious at three videos, genuinely painful at thirty, and claims sit on the
video earning nothing while they are open. This is the single easiest
operational mistake to make on an automated schedule, because nobody is
watching each upload land.

## Scheduling

Only once you've done a couple of weeks by hand. Cron the *build*, never the
publish:

```cron
0 4 * * * cd /path/to/projectV && /usr/bin/make new >> logs/build.log 2>&1
```

That leaves a finished private-ready episode waiting for your review each
morning. Automating `--publish` removes the only human checkpoint in the system.

## Calibration

After ~5 episodes:

```bash
python -m pipeline.cli calibrate
```

It measures your actual narration rate from rendered audio. Put the number in
`config/pipeline.yaml: target.words_per_minute`. The default of 143 is a
reasonable starting guess for this style at `speed: 0.94`, but voices differ by
10+ wpm and the error compounds into every episode's runtime.

## Render performance

Two passes: parallel per-shot Ken Burns clips, then a single xfade + mix pass.
The second is the one that hurts — it is effectively serial and it is where a
full-quality 10-minute 1080p render spends most of its time.

Reach for `--preview` (720p, fast preset, no grain) whenever you are checking
pacing rather than judging quality. If full renders are still too slow:

- `render.kb_upscale: 2 → 1` (drops zoompan resampling cost, adds slight
  stair-stepping on the move)
- `render.clip_preset: medium → fast`
- `render.grain_strength: 4 → 0` — grain is the biggest driver of output file
  size (strength 4 ≈ 2 Mbps, strength 7 ≈ 8.6 Mbps at 1080p30 CRF 19)

## Watching the voice quota

`make costs` reports characters used this month against your configured plan
and how many more episodes fit. The voice stage also warns before synthesising
an episode that would cross the allowance, so a surprise bill needs you to
ignore a message, not miss one.

Per-beat caching is what makes re-reads cheap: fixing one line costs that
line's characters, not the episode's 7,258.

## Health checks

```bash
make test        # assembly math still correct (catches crossfade drift)
make costs       # spend + ElevenLabs quota burn
make clean       # drop intermediate clips once episodes are published
```
