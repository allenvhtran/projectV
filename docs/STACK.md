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
| ElevenLabs Pro | $99 | 500k chars/mo |
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

### The ElevenLabs quota is the constraint to watch

A 10-minute episode is ~8,500 characters. Daily → ~255k chars/month, comfortably
inside Pro's 500k. But that leaves no room for re-reads: regenerating narration
for even a third of your episodes puts you near the ceiling, and overage is
billed per character. The pipeline caches per-beat audio precisely so a fix
costs one beat, not one episode. `python -m pipeline.cli costs` prints your
running character total.

## Sources

- [ElevenLabs pricing (2026)](https://bigvu.tv/blog/elevenlabs-pricing-2026-plans-credits-commercial-rights-api-costs/)
- [Midjourney API status (2026)](https://unifically.com/blogs/midjourney-api)
- [FLUX / image API pricing comparison](https://pricepertoken.com/image)
- [Official ElevenLabs MCP server](https://github.com/elevenlabs/elevenlabs-mcp)
