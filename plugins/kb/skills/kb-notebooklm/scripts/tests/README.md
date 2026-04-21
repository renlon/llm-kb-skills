# Tests for kb-notebooklm scripts

Hermetic unit tests for `assemble_audio.py`, `transcribe_audio.py`, and `postproc_hashing.py`.

## Running

```bash
source ~/notebooklm-py/.venv/bin/activate
pip install pytest                     # one-time, dev only
pytest plugins/kb/skills/kb-notebooklm/scripts/tests/ -v
```

`pytest` is intentionally not in `requirements.txt` — these tests are for developers, not for every KB project using the skill.

## What's tested

- Preflight clamping math (uses a small silent WAV generated at test time; skipped if ffmpeg absent).
- ffmpeg argv construction (string comparison, no subprocess exec).
- Timestamp formatting, VTT escaping, markdown merging.
- Diarization speaker labeling on synthetic data (whisper and pyannote are NOT loaded — we inject fake segments/turns).
- Hash stability and sensitivity.
- `postproc_complete` predicate across state matrices.

## What's NOT tested here

Real Whisper/pyannote model loading, real NotebookLM output, UI behavior in 小宇宙. Those are covered by the procedural checklist in `docs/superpowers/specs/2026-04-20-podcast-intro-hosts-transcript-design.md`.
