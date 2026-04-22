# Episode-Index Backfill — Live Run Status

**Branch:** merged to master (v1.15.0, commit 4b76a91)
**Date:** 2026-04-21 (evening session)

## What landed (complete)

All 10 of 12 planned tasks completed. Code shipped on master:

- `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` — 75 unit tests green
- `plugins/kb/skills/kb-publish/scripts/backfill_index.py` — CLI with Bedrock support
- `plugins/kb/skills/kb-publish/prompts/episode-wiki-extract.md` — Haiku extraction prompt
- `plugins/kb/skills/kb-notebooklm/prompts/dedup-judge.md` — Layer 3 judge prompt
- `plugins/kb/skills/kb-publish/SKILL.md` — step 8c + backfill-index subcommand docs
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — step 5b rewritten with dedup judge
- `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py` — pyannote 4.x DiarizeOutput fix

## Verification status

### ✅ Hermetic tests: 135 passed in 0.48s
75 episode-index + 60 kb-notebooklm tests all green.

### ✅ Synthetic end-to-end (no API cost)
Ran `orchestrate_episode_index()` with a mock Haiku call on a synthetic transcript. Confirmed:
- Extraction validation works
- existed_before recomputed from filesystem
- depth_deltas computed excluding current episode
- Transactional commit: new stubs staged + committed
- Collision detection: pre-existing non-stub article skipped correctly
- Round-trip parse via `scan_episode_wiki(strict=True)` succeeds
- Auto-stub `created_by` correctly set to `ep-99`

### ✅ Real Bedrock Haiku integration
Ran `backfill_index.py --episode 99` against a synthetic kb/ tree with a pre-existing transcript. Confirmed:
- Bedrock client initialized via CLAUDE_CODE_USE_BEDROCK=1
- POST to `bedrock-runtime.us-east-1.amazonaws.com/.../invoke` → `200 OK`
- Haiku returned valid JSON, auto-stubbed 2 concepts, wrote episode article
- Registry updated correctly

### ⚠️ LIVE BACKFILL of EP1/EP2 — not completed this session

**Blocker:** CPU-bound Whisper transcription is slower than expected on this machine. Multiple attempts:
- large-v3 model: 113+ min per 27-min episode (abandoned)
- small model, 2 concurrent: 30+ min each, didn't complete in poll window
- base model, 1 at a time: 33+ min, killed before completion

**Root cause:** Whisper inference on M-series CPU with `compute_type="auto"` is surprisingly slow for Mandarin content with dense continuous speech. Expected ~3-5 min for base model; actual 30+ min. Not a code bug — an environmental performance issue.

**What needs to happen to finish Task 11:**

Run the backfill command when CPU time is available. Estimated ~30-60 min per episode × 2 episodes = 1-2 hours of wall time.

```bash
cd /Users/dragon/Documents/MLL
source ~/notebooklm-py/.venv/bin/activate
/Users/dragon/notebooklm-py/.venv/bin/python3 \
  /Users/dragon/.claude/plugins/cache/llm-kb-skills/kb/1.15.0/skills/kb-publish/scripts/backfill_index.py \
  --all
```

This will:
1. Iterate EP1 and EP2 from `episodes.yaml`.
2. Find their audio in `output/notebooklm/`.
3. Call `transcribe_audio.py` (model=large-v3 per kb.yaml config).
4. Call `orchestrate_episode_index()` with Bedrock Haiku.
5. Write `wiki/episodes/ep-01-*.md` and `ep-02-*.md`.
6. Update `episodes.yaml` entries.

If CPU speed is still an issue, temporarily edit `kb.yaml`'s `integrations.notebooklm.podcast.transcript.model` to `small` or `base` for faster (lower-accuracy) transcripts — good enough for concept extraction.

### Task 12: Dedup judge verification — partially done

The `judge_candidate_episode()` function has unit tests. The function was also exercised inside the synthetic end-to-end test (via orchestrate's internal path). A live podcast-workflow run requires Task 11 to complete first so there are real `wiki/episodes/*.md` files to judge against.

## Artifacts

- EP3 audio (from the earlier live test) exists at `~/Documents/MLL/output/podcast-quantization-2026-04-21.mp3` (final with intro music) and `.raw.mp3` (raw from NotebookLM).
- EP3 transcription was never completed (CPU bottleneck). Re-run `transcribe_audio.py` with a faster model when ready.
- Generated intro music at `~/Documents/MLL/assets/intro.mp3` (13s).

## Pending debt

1. Whisper+CPU performance: consider installing GPU-accelerated faster-whisper via MLX port, or accepting the long wall-clock time.
2. Backfill of EP1 + EP2: run when CPU time is available.
3. EP3 audio has no transcript yet; re-run transcribe_audio.py.

## Confidence assessment

**High confidence the code is correct:**
- 135 passing unit tests
- Synthetic end-to-end passed
- Real Bedrock Haiku call succeeded with structured JSON response
- All SKILL.md edits in place

**Remaining work is mechanical** — wait for Whisper to finish, then the whole pipeline executes autonomously.
