# Tests for kb-publish episode-index scripts

Hermetic unit tests for `episode_wiki.py` and `backfill_index.py`.

## Running

```bash
source ~/notebooklm-py/.venv/bin/activate
pip install pytest    # dev-only; intentionally not in requirements.txt
pytest plugins/kb/skills/kb-publish/scripts/tests/ -v
```

## What's tested

- Pure helpers (validate_slug, slug_to_wiki_relative_path, compute_depth_deltas, etc.) — no filesystem.
- I/O helpers (scan_episode_wiki, concept_catalog) — tmp_path fixtures only.
- Transactional flow (index_episode_transactional) — Haiku is mocked.
- Rendering functions — snapshot tests.

## What's NOT tested here

Real Haiku/Anthropic API calls (gated to an opt-in integration test) and real audio transcription.
