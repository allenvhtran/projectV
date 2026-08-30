# Daily runbook

## The loop

```bash
make new                     # ~10-25 min wall clock, mostly ffmpeg
```

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

The per-shot Ken Burns pass is ~80% of wall clock and runs in parallel across
cores. If renders are too slow:

- `render.kb_upscale: 2 → 1` (drops zoompan resampling cost, adds slight
  stair-stepping on the move)
- `render.clip_preset: medium → fast`
- `render.grain_strength: 4 → 0` — grain is the biggest driver of output file
  size (strength 4 ≈ 2 Mbps, strength 7 ≈ 8.6 Mbps at 1080p30 CRF 19)

## Health checks

```bash
make test        # assembly math still correct (catches crossfade drift)
make costs       # spend + ElevenLabs quota burn
make clean       # drop intermediate clips once episodes are published
```
