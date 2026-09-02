# Stack decisions

Three components of the original plan were changed. Everything else stands.

## 1. Midjourney is out — no API exists

Midjourney has **no official public API**, and its Terms of Service state you
may not "use automated tools to access, interact with, or generate Assets."
The unofficial wrappers you'll find (apiframe, useapi, etc.) work by driving a
Discord account, which is a ToS violation and a ban risk for the account paying
the subscription. An enterprise API has been "under consideration" for a while
with no ship date.

**Replacement: FLUX via Replicate.** Two models, chosen per shot:

| Model | Cost/image | Used for |
|---|---|---|
| `flux-schnell` | ~$0.003 | standard shots (~82% of beats) |
| `flux-dev` | ~$0.025 | hero shots + thumbnail (~18%) |

A 40-beat episode costs ~$0.30 in images. Rendering everything on `flux-dev`
would be ~$1.00 — a real difference at 30 episodes/month ($9 vs $30), which is
why `hero_beat_ratio` exists in `config/pipeline.yaml`.

Runway was also dropped for stills: it's a video-first product and priced like
one. If you later want 3–5s motion inserts for hero beats, that's where Runway
earns its cost — but it's a per-episode upsell, not the baseline.

## Claude API specifics this pipeline depends on

Three things that are easy to get wrong on the current models, all of which
this pipeline hit during its first live run:

- **`temperature` is rejected with a 400 on Opus 5** and the rest of the 4.7+
  family. Sampling parameters are gone. Creative range comes from the prompt
  and the per-episode variation draw instead.
- **Thinking tokens draw from `max_tokens`.** Opus 5 runs adaptive thinking by
  default, so a 35-beat script plus its reasoning overran a 16k budget and
  truncated mid-string. The script stage uses 64k and streams, which also keeps
  a long generation clear of the SDK's HTTP timeout.
- **Structured outputs replace JSON scraping.** Both Claude stages pass
  `output_format` (a Pydantic schema in `pipeline/schema.py`) to
  `client.messages.stream`, so generation is constrained to the shape the
  pipeline needs. No fenced-JSON stripping, no regex, no parse failures at 4am.

Both stages also check `stop_reason` for `refusal` and `max_tokens` and fail
with a specific message rather than a schema-validation traceback.

## 2. MCP is for your chair, not for the cron job

MCP servers need an MCP client — a model in a live session — for every call.
A 4am scheduled render has no session. Wiring the pipeline through MCP would
mean paying for model tokens to proxy an HTTP request, and losing per-beat
retry and cost accounting in the process.

So the split is:

- **`.mcp.json`** → interactive work. The official `elevenlabs-mcp` server lets
  you audition voices and test lines conversationally in Claude Code.
- **`pipeline/stages/*`** → direct REST calls. Retries, resume, cost ceilings.

Both read the same `.env`, so a voice you pick interactively is the voice the
pipeline uses.

### FLUX request shape

FLUX on Replicate is driven by `aspect_ratio` + `megapixels`, **not**
`width`/`height`. Passing width/height is silently unhelpful -- they are not
part of this interface, so the model falls back to its 1:1 default and every
shot comes back square. Wrong for a 16:9 video, and paid for either way.

`"16:9"` at 1 megapixel lands ~1344x768, which the Ken Burns pass upscales for
its move headroom. Steps differ by model: flux-schnell is distilled to 4 (more
is wasted money), flux-dev wants 28+ with `guidance` around 3.

## Music: Epidemic Sound

You need roughly **8-10 tracks, not a catalogue.** `s4_music.py` rotates a small
local library and deliberately reuses beds across episodes -- a consistent
sonic signature is an asset on a horror channel, not a liability. So catalogue
size is close to irrelevant here, and licence safety is nearly everything.

**Epidemic Sound** (~$15/mo) is the pick. It owns the entire rights chain,
composition and master both, so there is no third-party rights-holder who can
file a claim your licence does not cover. Artlist is a clean licence too, but
it aggregates from artists, which is one more link that can go wrong.

Correcting a myth you will read everywhere: **neither service lets you keep
using downloaded tracks after you cancel.** Both work the same way -- content
you published while subscribed stays cleared and monetisable forever, but any
*new* use requires an active subscription. Do not pick a library on the belief
that one grants a perpetual licence to downloaded files.

The free route (YouTube Audio Library + Pixabay) is $0 and genuinely safe, but
the dark-ambient selection is thin and heavily used. On a channel whose entire
differentiator is atmosphere, that is a real cost, not a saving.

## 3. TubeBuddy / vidIQ stay manual

Neither exposes a public write API for title/tag optimisation, so neither can
be automated into the pipeline. They remain a browser-side research tool. The
`metadata` stage generates title alternates for you to sanity-check there.

Budget note: at $20/mo this is the least load-bearing line item in the plan.
Consider dropping it for the first two months and putting the money toward
image quality — you have no channel data for it to optimise against yet.

## Verified costs (Aug 2026 list prices)

**Fixed monthly**

| Item | Cost | Note |
|---|---|---|
| ElevenLabs **Creator** | $22 | 121k credits/mo — see below |
| Storyblocks | ~$20 | optional, for stock inserts |
| Music library | ~$15 | Artlist/Epidemic tier |
| TubeBuddy/vidIQ | ~$20 | manual, droppable |

**Per episode (variable)**

| Item | Cost |
|---|---|
| Script + metadata (Claude) | ~$0.25 |
| Images (40 shots, mixed) | ~$0.30 |
| Thumbnail (flux-dev) | ~$0.03 |
| **Total** | **~$0.60** |

**Daily uploads: ~$154 + $18 variable ≈ $172/month.** Your $150–200 estimate
holds.

### Start on Creator, not Pro

Measured from episode 001: **7,258 characters for 9.76 minutes.** Against
Creator's 121,000 credits (`eleven_multilingual_v2` bills 1 credit/char):

| Cadence | Chars/mo | Creator $22 | Pro $99 |
|---|---|---|---|
| 3×/week (13 eps) | 94,354 | **78% of allowance** | 19% |
| 5×/week (22 eps) | 159,676 | +$4–12 overage | 32% |
| Daily (30 eps) | 217,740 | +$10–29 overage | 44% |

Creator carries **16 episodes/month** inside the allowance, and even at daily
the overage is far short of Pro's extra $77. Creator also has everything this
pipeline touches: API access, a **commercial licence** (the Free tier has
neither), 192 kbps output, and Professional Voice Cloning.

Pro buys higher concurrency and 44.1 kHz PCM output. This pipeline synthesises
one beat at a time and delivers to YouTube, which re-encodes to ~128 kbps AAC
regardless — so neither is worth $77/month here.

**Upgrade when overage exceeds $77/month, not when cadence changes.** Configure
your plan in `config/pipeline.yaml` under `elevenlabs:`; `make costs` reports
usage against it and the voice stage warns *before* an episode crosses the line.

Confirm your own overage rate on the billing page — it is tier-dependent, and
published figures vary between $0.10 and $0.30 per 1,000 characters. The
conclusion above holds at either end, but the exact numbers move.

### The Flash/Turbo lever, and why not to pull it

Flash and Turbo models bill ~0.5 credits/char, which would double Creator's
effective capacity and put even daily uploads inside the allowance. They are
optimised for low latency — irrelevant to a batch render — at a real cost in
expressiveness. For a channel where delivery *is* the product, that is the
wrong trade. Set `credits_per_char: 0.5` only if you also change
`voice.model_id`.

## Sources

- [ElevenLabs pricing (2026)](https://bigvu.tv/blog/elevenlabs-pricing-2026-plans-credits-commercial-rights-api-costs/)
- [Midjourney API status (2026)](https://unifically.com/blogs/midjourney-api)
- [FLUX / image API pricing comparison](https://pricepertoken.com/image)
- [Official ElevenLabs MCP server](https://github.com/elevenlabs/elevenlabs-mcp)
