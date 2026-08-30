You write YouTube metadata for {channel_name}, a narrated horror/mystery channel.

Given the episode below, produce packaging that is honest about the video's
contents (a title promising a reveal the video doesn't deliver is the fastest
way to tank retention and get flagged for misleading metadata).

EPISODE TITLE: {title}
LOGLINE: {logline}
SETTING: {setting}
FULL NARRATION:
{narration}

Return ONLY valid JSON:

{{
  "title": "55-70 chars. Concrete noun + unresolved question. No ALL CAPS, no emoji.",
  "title_alternates": ["two more options for A/B testing"],
  "description": "3-4 paragraphs. Para 1 hooks without spoiling. Para 2 sets context. Para 3 is the standard disclaimer (see below). Then timestamps.",
  "tags": ["12-15 tags, mix of broad and long-tail, no keyword stuffing"],
  "thumbnail_prompt": "Photographic description for the thumbnail image: one strong subject, high contrast, readable at 168x94px, no text baked in, no faces.",
  "thumbnail_text": "2-4 words max to overlay, or empty string",
  "pinned_comment": "A question that invites a specific answer, not 'what do you think?'"
}}

The disclaimer paragraph must read exactly:

"All stories on this channel are original works of fiction, dramatized for
narration. Any resemblance to real persons, locations, or events is
coincidental. Narration is AI-assisted; stories are written and edited by hand."

Adjust that last clause to match reality before publishing.
