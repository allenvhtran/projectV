# The policy risk this pipeline is built around

Read this before your first upload. It's the single biggest threat to the plan,
and it is structural — not something you fix later with better prompts.

## What changed

YouTube's policy formerly called "repetitious content" became "inauthentic
content" in July 2025 and **"Generic or Repetitive Content"** in July 2026. It
targets content that is:

- mass-produced or repetitive,
- made from a template with little to no variation across videos,
- **easily replicable at scale.**

In January 2026 YouTube removed sixteen channels with ~35M combined subscribers
and ~4.7B lifetime views. All sixteen were faceless.

## What this does and doesn't mean

**It does not mean AI-assisted or faceless content is banned.** YouTube has been
consistent that the policy is tool-agnostic — it judges the finished video, not
how it was made. There is no rule requiring a face on camera, AI-labelled videos
are not suppressed in recommendations, and faceless channels are monetised
every day.

**It does mean the exact artifact a naive daily pipeline produces is the target
case.** "AI narration over stills, identical structure every episode, shipped at
volume" is close to a verbatim description of what gets flagged. The risk isn't
that you used automation; it's that automation with no variation produces output
whose whole value proposition is scale.

The distinction YouTube draws is whether each video carries commentary, insight,
or narrative a template could not produce.

## What the pipeline does about it

`config/pipeline.yaml` has a `variation` block that is load-bearing, not
decoration. Every episode draws:

- one of **6 narrative structures** (nested document, reverse reveal, two
  disagreeing accounts, procedural, recurrence, linear),
- one of **4 cold-open styles**,
- one of **4 resolution types**,
- a setting from a pool,
- a **runtime jitter** of −1.5 to +2.5 minutes.

`pipeline/variation.py` refuses to reuse a value used in the last 12 episodes,
falling back to least-recently-used only when the pool is exhausted. Every
choice is recorded in the episode manifest, so the variation is auditable.

That's ~576 structural combinations before setting and runtime. Two consecutive
episodes will not share a skeleton, and a month of episodes will not have the
same shape or the same length.

The prompt in `prompts/story.md` also bans the genre's tell-tale filler
("little did they know", "chilling", "what happened next will…") and requires
specificity over adjectives, because the stock phrasing is itself a template
signal.

## What the pipeline cannot do for you

Be honest about this part. Structural variation raises the floor; it does not
clear the bar on its own. Three things still need you:

1. **Read every script before it ships.** The `new` command deliberately stops
   before upload, and `upload` defaults to `privacyStatus: private`. Both are
   friction on purpose. A script you have actually read and edited is the
   difference between "AI-assisted" and "mass-produced".

2. **Don't ship daily out of the gate.** Daily upload is the highest-risk
   cadence on the least channel history. 3×/week for the first two months
   gives you time to edit properly and gives the channel a track record before
   volume. The pipeline doesn't care about cadence; your cron schedule does.

3. **Add something a template can't.** The strongest version of this channel
   isn't fully automatic. Research into a real category of place, an original
   framing device per episode, your own edit pass on the narration — that's what
   the policy is actually asking for, and it's the part worth your hours.

## Disclosure

The upload stage sets `containsSyntheticMedia: true` unconditionally. Narration
is synthetic and the stills are generated; disclosing realistic synthetic media
is required, and the label does not affect monetisation or reach. Don't remove
it — an undisclosed AI channel that gets noticed has a much worse problem than a
labelled one.

The standard description disclaimer in `prompts/metadata.md` says stories are
"written and edited by hand." **Make that true or change the wording.** An
inaccurate disclaimer is worse than none.

## Sources

- [YouTube inauthentic content policy explained](https://newmoneymatrix.org/youtube-inauthentic-content-policy-explained/)
- [Real rules vs. made-up ones](https://ytgrowth.io/blog/youtube-ai-policy)
- [Why YouTube suspended thousands of AI channels](https://milx.app/en/news/why-youtube-just-suspended-thousands-of-ai-channels-and-how-to-protect-yours)
