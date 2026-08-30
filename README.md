# projectV — faceless horror/mystery video pipeline

Script → narration → stills → assembled 10-minute video → YouTube, as seven
resumable stages driven by one CLI.

```
prompts/story.md ─► [script]  Claude API        → beats (narration + image prompt)
                    [voice]   ElevenLabs        → one mp3 per beat, real durations
                    [visuals] Replicate / FLUX  → one still per beat
                    [music]   local library     → rotated ambient bed
                    [assemble] ffmpeg           → Ken Burns + xfade + ducked mix
                    [metadata] Claude + FLUX    → title, tags, chapters, thumbnail
                    [upload]  YouTube Data v3   → private by default
```

**A beat is the atomic unit: one narration chunk = one image = one shot.** The
script model emits beats directly, so audio/visual sync falls out of the data
instead of needing forced alignment after the fact.

## Quickstart

```bash
make setup                      # deps + ffmpeg check + .env scaffold
$EDITOR .env                    # add your 4 keys
make test                       # end-to-end assembly check, no keys needed

python -m pipeline.cli voices   # pick a narrator, paste id into .env
make new                        # build an episode (stops before upload)
python -m pipeline.cli auth     # one-time YouTube OAuth
make upload                     # uploads PRIVATE. review, then publish
```

Read **[docs/ORIGINALITY.md](docs/ORIGINALITY.md) before your first upload** —
it covers the YouTube policy that this pipeline's architecture is a response to.
[docs/STACK.md](docs/STACK.md) explains three changes made to the original plan
(Midjourney has no API, MCP isn't for cron jobs, TubeBuddy stays manual).

## Everything is resumable

Each stage checks the manifest and skips work that's already done. A crash at
assembly costs you an ffmpeg run, never another round of TTS or image spend.

```bash
python -m pipeline.cli run                          # resume where it stopped
python -m pipeline.cli run --stage assemble --force # re-render only
python -m pipeline.cli run --slug ep004-... --stage visuals --force
```

To re-read one bad line: delete `episodes/<slug>/audio/beat_017.mp3`, then
`run --stage voice`. It regenerates that beat alone and rebuilds the timeline.

## Layout

```
config/channel.yaml      channel identity, voice settings, render knobs
config/pipeline.yaml     runtime targets, variation pools, cost ceilings
prompts/                 story + metadata prompt templates
pipeline/stages/         one module per stage, s1..s7
pipeline/variation.py    picks a structure unused in the last 12 episodes
pipeline/costs.py        per-episode and per-month hard ceilings
episodes/<slug>/         manifest.json + audio/ images/ clips/ meta/ + the mp4
scripts/smoke_test.py    synthetic end-to-end assembly test
```

`episodes/<slug>/manifest.json` is the single source of truth for an episode:
variation choices, beats, timeline, costs, stage status, YouTube id.

## Cost control

Hard ceilings in `config/pipeline.yaml` abort the run rather than overspend
silently ($3.00/episode, $220/month). `make costs` prints month-to-date spend
and your ElevenLabs character consumption, which is the quota that actually
binds — see [docs/STACK.md](docs/STACK.md).

Expect **~$0.60/episode variable, ~$172/month all-in** at daily cadence.

## Requirements

Python 3.10+, ffmpeg on PATH (`brew install ffmpeg` / `apt install ffmpeg`;
`pip install imageio-ffmpeg` works as a fallback). Keys: Anthropic, ElevenLabs,
Replicate, and a Google OAuth desktop client for uploads.
