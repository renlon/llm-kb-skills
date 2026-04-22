You are judging whether a proposed new podcast episode would duplicate
content the show has already published. The show covers AI/ML engineering
topics in Mandarin. The audience is engineers who want to learn deeply; they
do not want the same topic repeated at the same depth. They DO want
deeper-dive follow-ups on topics previously covered at shallower depth, and
they love when a new episode pays off a thread hinted at in a past episode.

## Inputs

### Proposed candidate concepts for the new episode

{candidates}

### Prior coverage per candidate (from already-published episodes)

Each entry is `candidate_name: [{ep_id, depth, key_points}]`. Empty array means
no prior coverage.

{prior_hits}

### Open threads from recent episodes (promises the show has hinted at)

{open_threads}

## Task

Produce exactly ONE JSON object with these fields:

- `per_concept` (array): one entry per candidate with:
  - `candidate` (string): echo of the candidate name.
  - `verdict`: one of
    - `"novel"` — no prior coverage
    - `"deeper_dive"` — prior episode covered at shallower depth; new episode adds value
    - `"addresses_open_thread"` — the candidate answers a promised thread from a past episode
    - `"redundant_same_depth"` — prior episode already covered at this depth; do NOT re-cover
    - `"redundant_key_points"` — prior episode already taught the specific key_points proposed
  - `reasoning` (string): ONE SENTENCE explaining the verdict.
  - `recommended_framing` (string): ONE SENTENCE of advice. For redundant verdicts, usually "skip this concept; reference EP-N instead." For deeper_dive, usually "open with a callback to EP-N, then go deeper on X."
- `episode_verdict`: one of `"proceed"`, `"reframe"`, `"skip"`.
- `framing_recommendation` (string): if proceeding, what angle or depth makes this episode distinct. Short paragraph.

## Rules

- Be strict on `redundant_same_depth`. A candidate whose prior_hits show same-or-greater depth AND overlapping key_points is redundant, full stop.
- `deeper_dive` requires depth delta. Introducing the same concept at the same depth is NOT a deeper dive.
- When `open_threads` contains a note whose text obviously matches a candidate, prefer `addresses_open_thread` over `novel`.
- **Output ONLY the JSON object.** No markdown, no prose, no fences.
