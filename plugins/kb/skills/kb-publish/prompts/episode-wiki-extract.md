You are extracting a structured concept inventory from a podcast transcript
for a dedup index. The audience of this index is the same team that wrote
and published the podcast; the goal is to prevent accidentally covering the
same concept twice, and to spot "deeper-dive" opportunities on topics
previously introduced at shallower depth.

## Inputs

### Episode metadata

{episode_metadata}

### Transcript

{transcript}

### Existing wiki concept articles (canonical targets for wikilinks)

{concept_catalog}

### Recent episodes (for canonicalization context)

{recent_episodes}

## Task

Produce exactly ONE JSON object with these fields:

- `summary` (string): 1-2 paragraph elevator pitch of what this episode actually taught.
- `concepts` (array): each entry describes one concept taught in the episode with fields:
  - `slug` (string): vault-relative wiki slug WITH the `wiki/` prefix, NO `.md` extension. Must match an existing concept catalog entry when possible; otherwise propose a new slug following the catalog's naming convention.
  - `depth_this_episode`: one of `"mentioned"`, `"explained"`, `"deep-dive"`.
  - `what` (string): ONE-SENTENCE definition as taught in this episode.
  - `why_it_matters` (string): ONE-SENTENCE reason this concept matters.
  - `key_points` (array of strings): 1-3 specific teaching claims actually made in this episode. These should be so specific that someone proposing to re-teach the exact same claims next week would obviously repeat you. Generic summaries like "Flash Attention is fast" are NOT acceptable.
  - `covered_at_sec` (number): seconds into the transcript where the concept is first substantively discussed. Best-effort estimate; never null.
  - `existed_before` (boolean): true if the slug already appears in the concept catalog. (The system re-checks this, so err toward false if unsure.)
- `open_threads` (array): topics hinted at but not substantively covered. Each entry is an object with:
  - `slug` (string or null): wikilink target if a reasonable one exists, otherwise null.
  - `note` (string): short description of the thread.
  - `existed_before` (boolean).
- `series_links`:
  - `builds_on` (array of strings): wiki slugs of past episodes this episode builds on (`wiki/episodes/ep-N-...`).
  - `followup_candidates` (array of strings): natural next-episode topics.

## Rules

- **Canonicalize aggressively.** Match transcript concepts to catalog slugs whenever possible. Use the SAME slug; don't fork a new one just because the wording differs.
- 15-40 concepts per episode. Fewer for intro; more for deep-dive.
- A concept counts as "explained" only if there's a defining statement AND at least one follow-up elaboration. A passing mention is "mentioned".
- "deep-dive" requires sustained discussion: definition, mechanics, examples, tradeoffs.
- `key_points` must be specific. Not "quantization is useful" — something like "k-quants groups 32-256 element blocks with per-group scale to avoid outlier range-collapse."
- `open_threads` = future-episode candidates. Don't pad.
- **AUDIENCE AND CONFIDENTIALITY:** Source transcripts may have been sanitized from internal lessons; do NOT invent proprietary product or company names. If a concept in the transcript is generic ("an LLM serving system"), keep it generic in the slug and description.
- **Output ONLY the JSON object.** No prose, no markdown fences, no commentary.
