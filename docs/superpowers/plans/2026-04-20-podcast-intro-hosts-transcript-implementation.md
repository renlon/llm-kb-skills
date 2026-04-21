# Podcast Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3s-crossfade intro music, named hosts (瓜瓜龙 / 海发菜), and speaker-labeled transcripts to the `kb-notebooklm` podcast workflow, and fix the "My Lessons Learned" brand leak so the on-air brand is 全栈AI.

**Architecture:** Two new Python scripts (`assemble_audio.py` using ffmpeg acrossfade, `transcribe_audio.py` using faster-whisper + pyannote diarization) live under the skill's `scripts/` directory. A shared `postproc_hashing.py` module provides deterministic hashing used by both the scripts' tests and eventually by the skill's dedup logic (though the skill itself is prose, not Python — the shared module exists for test coverage of the algorithm). The skill's podcast workflow is extended in-place: prompt rendering moves before hashing so host/brand changes bust `params_hash`, a new `postproc_hash` + `postproc_complete` predicate governs when post-processing can re-run without regenerating from NotebookLM, and the background agent now assembles (or copies) then transcribes using the actual VTT offset derived from assembly outcome.

**Tech Stack:**
- Python 3 scripts (stdlib + faster-whisper + pyannote.audio + PyYAML), invoked via the existing `notebooklm-py` venv (`~/notebooklm-py/.venv`)
- ffmpeg / ffprobe (via `subprocess`, CLI already installed at `/opt/homebrew/bin/ffmpeg`)
- pytest for unit tests (new dependency in dev-only requirements)
- Whisper large-v3 model reused from existing HuggingFace cache at `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3` (prior VoxToriApp download)
- Pyannote `speaker-diarization-3.1` + `segmentation-3.0` (both gated; downloaded on first run after license acceptance)

---

## File Structure

### New files

- `plugins/kb/skills/kb-notebooklm/scripts/__init__.py` — marks the scripts dir as a package so tests can import helpers.
- `plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py` — CLI: ffmpeg preflight + crossfade + JSON status.
- `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py` — CLI: faster-whisper + pyannote + VTT/markdown emission.
- `plugins/kb/skills/kb-notebooklm/scripts/postproc_hashing.py` — pure-python helpers for `params_hash`, `postproc_hash`, `postproc_complete` predicate. Imported by both scripts (for deterministic testing) and referenced by the skill prompt (so the skill can direct Claude to call it via `python3 -m`).
- `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt` — pins `faster-whisper>=1.0.0`, `pyannote.audio>=3.1.0`, `PyYAML>=6.0`.
- `plugins/kb/skills/kb-notebooklm/scripts/tests/__init__.py` — test package marker.
- `plugins/kb/skills/kb-notebooklm/scripts/tests/conftest.py` — shared pytest fixtures (synthetic whisper/diarization data, tmp intro files).
- `plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py` — preflight math, ffmpeg argv building, JSON shape.
- `plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py` — timestamp formatting, VTT escaping, markdown merging, diarization labeling, segment splitting, offset sanity, self-intro swap, title derivation.
- `plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py` — hash stability/sensitivity + completeness predicate.
- `plugins/kb/skills/kb-notebooklm/scripts/tests/README.md` — how to run tests.

### Modified files

- `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md` — brand fix, `{hosts}` placeholder, HOST INTRODUCTION section.
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — steps 6a', 6b', 6c dedup, 6i prompt injection, 6k background agent, step 7 sidecar, cleanup workflow.
- `plugins/kb/skills/kb-publish/SKILL.md` — sidecar import (Step 2b) + registry update (Step 8b) preserve new fields.
- `plugins/kb/skills/kb-init/SKILL.md` — new venv deps, ffmpeg check, pyannote license prompts, persisted `transcript.enabled`.
- `plugins/kb/.claude-plugin/plugin.json` — version bump (patch).

---

## Test Strategy

**Unit tests (pytest, hermetic).** Cover the Python helpers: ffmpeg argv construction, preflight clamping math, timestamp formatting, VTT escaping, speaker labeling with synthetic whisper+diarization data, hash stability/sensitivity, completeness predicate. No network, no model loading.

**Integration tests (manual, human-in-the-loop).** Procedural end-to-end verifications listed in the spec under "Testing & Verification" — require real intro music, real NotebookLM generation, real audio playback. These are documented as a checklist but not automated.

Tests live in `plugins/kb/skills/kb-notebooklm/scripts/tests/`. Run with:

```bash
source ~/notebooklm-py/.venv/bin/activate && \
  pip install pytest && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/ -v
```

`pytest` is intentionally NOT added to `scripts/requirements.txt` — it's a dev-time dependency, installed ad hoc. Document that clearly in the tests/README.md.

The `transcribe_audio.py` tests for Whisper/pyannote integration use **monkeypatched stubs** — we inject fake segment and diarization objects rather than loading real models. The script's structure must expose two seams: a `transcribe_audio(audio_path, model, device, language)` function returning whisper segments (mockable), and a `diarize_audio(audio_path, hf_token)` function returning diarization turns (mockable). The CLI `main()` composes them.

`assemble_audio.py` tests shell out to `ffprobe` for duration detection — this is the only integration test that touches a real binary. Generate a 3-second silent WAV in the test via `ffmpeg -f lavfi -i anullsrc=r=16000 -t 3 {tmp}.wav` and assert preflight math. This requires ffmpeg to be on PATH; skip the test with a clear message if not.

---

## Task Order Rationale

Tasks are ordered so each produces a self-contained, testable artifact and later tasks build on earlier ones without reordering dependencies:

1. **Task 1:** Create the scripts package skeleton + tests directory. Minimal surface so later tasks can add files into an existing layout.
2. **Task 2:** Implement `postproc_hashing.py` with full test coverage. Pure-python, no external dependencies, trivial to test. Used by later scripts.
3. **Task 3:** Implement `assemble_audio.py`. Isolatable — only depends on ffmpeg CLI, no ML models. Ships the intro-music feature end-to-end.
4. **Task 4:** Implement `transcribe_audio.py`. Depends on faster-whisper + pyannote; most complex unit. Ships the transcription feature.
5. **Task 5:** Update `prompts/podcast-tutor.md` (brand + hosts). Pure text change, no runtime dependencies. Ships the brand fix even if later tasks are incomplete.
6. **Task 6:** Update `SKILL.md` — workflow reorder, `postproc_hash`, `podcast_outputs`, new background-agent prompt, cleanup updates. Wires the scripts into the skill.
7. **Task 7:** Update `kb-publish/SKILL.md` to preserve new sidecar fields.
8. **Task 8:** Update `kb-init/SKILL.md` for one-time setup (deps, ffmpeg, HF tokens).
9. **Task 9:** Version bump + final commit.

Tasks 3 and 4 could run in parallel if desired, but we serialize them so the subagent orchestrator sees a clean linear plan. Task 5 is intentionally placed after the scripts because the prompt change technically ships usefully on its own, but it's easier to review once the runtime plumbing exists — the prompt is short and this avoids another standalone review cycle.

---

## Task 1: Scaffold scripts package and test layout

**Goal:** Create the directory structure so subsequent tasks only add files into an existing tree.

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/scripts/__init__.py`
- Create: `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt`
- Create: `plugins/kb/skills/kb-notebooklm/scripts/tests/__init__.py`
- Create: `plugins/kb/skills/kb-notebooklm/scripts/tests/conftest.py`
- Create: `plugins/kb/skills/kb-notebooklm/scripts/tests/README.md`

- [ ] **Step 1: Create empty package markers**

Create `plugins/kb/skills/kb-notebooklm/scripts/__init__.py` with contents:

```python
```

(A single newline — empty file, just marks the directory as a Python package.)

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/__init__.py` with the same empty content.

- [ ] **Step 2: Write requirements.txt**

Create `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt` with:

```
faster-whisper>=1.0.0
pyannote.audio>=3.1.0
PyYAML>=6.0
```

Note: `pytest` is intentionally omitted. It's a dev-time dependency, installed manually when running tests.

- [ ] **Step 3: Write tests/conftest.py with shared fixtures**

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/conftest.py`:

```python
"""Shared pytest fixtures for kb-notebooklm script tests.

Synthetic whisper/diarization data and helpers for generating test audio files.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def ffmpeg_required():
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not on PATH")


@pytest.fixture
def silent_wav(tmp_path: Path, ffmpeg_required) -> Path:
    """Generate a 3-second silent WAV for ffprobe duration tests."""
    out = tmp_path / "silent_3s.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "3", str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def silent_wav_factory(tmp_path: Path, ffmpeg_required):
    """Factory for generating silent WAVs of arbitrary durations."""
    def _make(seconds: float, name: str = "silent.wav") -> Path:
        out = tmp_path / name
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", str(seconds), str(out),
            ],
            check=True,
        )
        return out
    return _make


@pytest.fixture
def fake_whisper_segment():
    """Build a whisper-like segment dict for alignment tests."""
    def _make(start: float, end: float, text: str, words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if words is None:
            # Evenly distribute words across the segment window.
            tokens = text.split()
            if not tokens:
                tokens = [text]
            step = (end - start) / len(tokens)
            words = [
                {"start": start + i * step, "end": start + (i + 1) * step, "word": tok}
                for i, tok in enumerate(tokens)
            ]
        return {"start": start, "end": end, "text": text, "words": words}
    return _make


@pytest.fixture
def fake_diarization_turn():
    """Build a diarization turn dict for alignment tests."""
    def _make(start: float, end: float, speaker: str) -> dict[str, Any]:
        return {"start": start, "end": end, "speaker": speaker}
    return _make
```

- [ ] **Step 4: Write tests/README.md**

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/README.md`:

```markdown
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
```

- [ ] **Step 5: Verify directory layout**

Run:

```bash
ls plugins/kb/skills/kb-notebooklm/scripts/
ls plugins/kb/skills/kb-notebooklm/scripts/tests/
```

Expected output (scripts/): `__init__.py requirements.txt tests`
Expected output (tests/): `README.md __init__.py conftest.py`

- [ ] **Step 6: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/scripts/
git commit -m "feat(kb-notebooklm): scaffold scripts package and test layout

Adds empty __init__.py markers, requirements.txt, shared pytest fixtures
(conftest.py), and a tests/README.md documenting how to run the suite.
No runtime behavior yet — later tasks add assemble_audio.py,
transcribe_audio.py, and postproc_hashing.py into this tree."
```

---

## Task 2: Implement `postproc_hashing.py` with full test coverage

**Goal:** Provide deterministic hashing helpers used by the skill prose (which will shell out to `python3 -m plugins.kb.skills.kb-notebooklm.scripts.postproc_hashing`) and by script tests. Pure Python, no external deps.

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/scripts/postproc_hashing.py`
- Test: `plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py`

- [ ] **Step 1: Write the failing test file**

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py`:

```python
"""Tests for postproc_hashing: params_hash, postproc_hash, postproc_complete."""
from __future__ import annotations

from pathlib import Path

import pytest

from plugins.kb.skills.kb_notebooklm.scripts import postproc_hashing as H


# ------------------------------
# params_hash
# ------------------------------

def _base_params():
    return {
        "format": "deep-dive",
        "length": "default",
        "language": "zh",
        "rendered_prompt": "This is an episode of 全栈AI ...\n{lessons}",
        "host_pool": ["瓜瓜龙", "海发菜"],
    }


def test_params_hash_is_deterministic():
    p = _base_params()
    assert H.params_hash(**p) == H.params_hash(**p)


def test_params_hash_changes_when_host_pool_changes():
    h1 = H.params_hash(**_base_params())
    p2 = _base_params()
    p2["host_pool"] = ["瓜瓜龙", "玉米糖"]
    assert H.params_hash(**p2) != h1


def test_params_hash_changes_when_prompt_changes():
    h1 = H.params_hash(**_base_params())
    p2 = _base_params()
    p2["rendered_prompt"] += "\n# new line"
    assert H.params_hash(**p2) != h1


def test_params_hash_changes_when_format_changes():
    h1 = H.params_hash(**_base_params())
    p2 = _base_params()
    p2["format"] = "brief"
    assert H.params_hash(**p2) != h1


def test_params_hash_stable_regardless_of_post_processing_settings():
    """Intro music + transcript config must NOT flow into params_hash."""
    base = H.params_hash(**_base_params())
    # No postproc settings are even accepted by params_hash — this is a type-level check.
    # Ensure the function signature rejects extras.
    with pytest.raises(TypeError):
        H.params_hash(**_base_params(), intro_music_path="/x.mp3")  # type: ignore[call-arg]
    assert base == H.params_hash(**_base_params())


# ------------------------------
# postproc_hash
# ------------------------------

def _base_postproc(intro_path: str | None = None):
    return {
        "intro_music_path": intro_path,
        "intro_music_mtime": 1_700_000_000.0 if intro_path else None,
        "intro_music_size": 123_456 if intro_path else None,
        "intro_music_content_sha256": "a" * 64 if intro_path else None,
        "requested_intro_length": 12.0,
        "requested_crossfade_seconds": 3.0,
        "effective_intro_length": 12.0,
        "effective_crossfade": 3.0,
        "transcript_enabled": True,
        "transcript_model": "large-v3",
        "transcript_language": "zh",
        "host_pool": ["瓜瓜龙", "海发菜"],
    }


def test_postproc_hash_is_deterministic():
    p = _base_postproc("/x.mp3")
    assert H.postproc_hash(**p) == H.postproc_hash(**p)


def test_postproc_hash_changes_when_intro_content_sha_changes():
    h1 = H.postproc_hash(**_base_postproc("/x.mp3"))
    p2 = _base_postproc("/x.mp3")
    p2["intro_music_content_sha256"] = "b" * 64
    assert H.postproc_hash(**p2) != h1


def test_postproc_hash_changes_when_intro_size_changes():
    h1 = H.postproc_hash(**_base_postproc("/x.mp3"))
    p2 = _base_postproc("/x.mp3")
    p2["intro_music_size"] = 999
    assert H.postproc_hash(**p2) != h1


def test_postproc_hash_changes_when_requested_values_differ_but_effective_same():
    """Config-intent check: bumping requested_crossfade must bust hash even if clamping collapses."""
    h1 = H.postproc_hash(**_base_postproc("/x.mp3"))
    p2 = _base_postproc("/x.mp3")
    p2["requested_crossfade_seconds"] = 2.0
    # Effective is still 3.0 (e.g., clamp didn't trigger at these values) — but requested changed.
    assert H.postproc_hash(**p2) != h1


def test_postproc_hash_changes_when_transcript_disabled():
    h1 = H.postproc_hash(**_base_postproc("/x.mp3"))
    p2 = _base_postproc("/x.mp3")
    p2["transcript_enabled"] = False
    assert H.postproc_hash(**p2) != h1


def test_postproc_hash_handles_none_intro_deterministically():
    p1 = _base_postproc(None)
    p2 = _base_postproc(None)
    assert H.postproc_hash(**p1) == H.postproc_hash(**p2)


# ------------------------------
# postproc_complete predicate
# ------------------------------

def _run_outputs(tmp_path: Path, intro: bool = True, transcript: bool = True, create_files: bool = True):
    raw = tmp_path / "x.raw.mp3"
    final = tmp_path / "x.mp3"
    vtt = tmp_path / "x.vtt"
    md = tmp_path / "x.transcript.md"
    manifest = tmp_path / "x.mp3.manifest.yaml"
    if create_files:
        for p in (raw, final, vtt, md):
            p.write_bytes(b"x")
    return {
        "raw_audio": str(raw),
        "final_audio": str(final),
        "vtt": str(vtt) if transcript else None,
        "transcript_md": str(md) if transcript else None,
        "manifest": str(manifest),  # never created in test; must not affect predicate
        "intro_applied": intro,
        "transcript_applied": transcript,
    }


def test_postproc_complete_true_when_all_files_present(tmp_path):
    outputs = _run_outputs(tmp_path, intro=True, transcript=True, create_files=True)
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is True


def test_postproc_complete_false_when_final_audio_missing(tmp_path):
    outputs = _run_outputs(tmp_path, intro=True, transcript=True, create_files=True)
    Path(outputs["final_audio"]).unlink()
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is False


def test_postproc_complete_false_when_intro_configured_but_not_applied(tmp_path):
    outputs = _run_outputs(tmp_path, intro=False, transcript=True, create_files=True)
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is False


def test_postproc_complete_true_when_intro_not_configured(tmp_path):
    outputs = _run_outputs(tmp_path, intro=False, transcript=True, create_files=True)
    assert H.postproc_complete(outputs, intro_music_configured=False, transcript_enabled=True) is True


def test_postproc_complete_false_when_transcript_enabled_but_not_applied(tmp_path):
    outputs = _run_outputs(tmp_path, intro=True, transcript=False, create_files=True)
    # Files don't exist for vtt/md (set to None)
    outputs["vtt"] = None
    outputs["transcript_md"] = None
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is False


def test_postproc_complete_true_when_transcript_disabled(tmp_path):
    outputs = _run_outputs(tmp_path, intro=True, transcript=False, create_files=True)
    outputs["vtt"] = None
    outputs["transcript_md"] = None
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=False) is True


def test_postproc_complete_ignores_missing_manifest(tmp_path):
    """manifest is transient (kb-publish deletes it) — must not affect predicate."""
    outputs = _run_outputs(tmp_path, intro=True, transcript=True, create_files=True)
    # Manifest was never created in _run_outputs. Must still return True.
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is True


def test_postproc_complete_false_when_vtt_file_missing(tmp_path):
    outputs = _run_outputs(tmp_path, intro=True, transcript=True, create_files=True)
    Path(outputs["vtt"]).unlink()
    assert H.postproc_complete(outputs, intro_music_configured=True, transcript_enabled=True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source ~/notebooklm-py/.venv/bin/activate && \
  pip install pytest -q && \
  cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py -v
```

Expected: ImportError / module-not-found on `postproc_hashing`, or collection error — 0 tests pass.

Note: Because Python's import machinery sees `plugins.kb.skills.kb-notebooklm` (hyphen in package name) as invalid, ensure both the `scripts/__init__.py` created in Task 1 AND the import path used in the test file (`plugins.kb.skills.kb_notebooklm.scripts.postproc_hashing`) use underscore. If the actual on-disk directory is `kb-notebooklm` (hyphen), the tests must import via `importlib` with the hyphen path. Fix this now:

Edit `plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py` and replace the top-of-file import:

```python
from plugins.kb.skills.kb_notebooklm.scripts import postproc_hashing as H
```

with:

```python
import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import postproc_hashing as H  # noqa: E402
```

This makes the import work regardless of Python package naming with hyphens. Apply the same pattern to every test file in this plan whenever it imports from scripts. Re-run the failing-test command to confirm the import path now resolves but the module is missing.

Expected: collection error `ModuleNotFoundError: No module named 'postproc_hashing'`.

- [ ] **Step 3: Implement `postproc_hashing.py`**

Create `plugins/kb/skills/kb-notebooklm/scripts/postproc_hashing.py`:

```python
"""Deterministic hashing and completeness helpers for kb-notebooklm post-processing.

These helpers give the skill's dedup logic a stable, testable representation of
what's been done and what settings it was done with. See
`docs/superpowers/specs/2026-04-20-podcast-intro-hosts-transcript-design.md`
sections 6 and 7 for the semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def params_hash(
    *,
    format: str,
    length: str,
    language: str,
    rendered_prompt: str,
    host_pool: list[str],
) -> str:
    """Hash of prompt-affecting generation settings.

    Changes here force NotebookLM regeneration.
    """
    parts = [
        format,
        length,
        language,
        _sha256_hex(rendered_prompt),
        json.dumps(host_pool[:2], ensure_ascii=False, sort_keys=False),
    ]
    return _sha256_hex("\x1f".join(parts))


def postproc_hash(
    *,
    intro_music_path: str | None,
    intro_music_mtime: float | None,
    intro_music_size: int | None,
    intro_music_content_sha256: str | None,
    requested_intro_length: float,
    requested_crossfade_seconds: float,
    effective_intro_length: float,
    effective_crossfade: float,
    transcript_enabled: bool,
    transcript_model: str,
    transcript_language: str,
    host_pool: list[str],
) -> str:
    """Hash of post-processing settings.

    Changes here mean we can re-run post-processing only (assembly + transcription),
    without hitting NotebookLM again.
    """
    def _str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            # Fixed-precision avoids tiny-FP drift between runs.
            return f"{value:.6f}"
        return str(value)

    parts = [
        _str(intro_music_path),
        _str(intro_music_mtime),
        _str(intro_music_size),
        _str(intro_music_content_sha256),
        _str(requested_intro_length),
        _str(requested_crossfade_seconds),
        _str(effective_intro_length),
        _str(effective_crossfade),
        _str(transcript_enabled),
        _str(transcript_model),
        _str(transcript_language),
        json.dumps(host_pool, ensure_ascii=False, sort_keys=False),
    ]
    return _sha256_hex("\x1f".join(parts))


def hash_intro_file(path: str | os.PathLike[str]) -> tuple[float, int, str]:
    """Return (mtime, size, sha256_hex) for an intro file. Raises FileNotFoundError if missing."""
    p = Path(path)
    stat = p.stat()
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return (stat.st_mtime, stat.st_size, h.hexdigest())


def postproc_complete(
    outputs: Mapping[str, Any],
    *,
    intro_music_configured: bool,
    transcript_enabled: bool,
) -> bool:
    """Return True iff the stored run outputs satisfy the configured features.

    `outputs` is a dict with keys: raw_audio, final_audio, vtt, transcript_md,
    manifest, intro_applied, transcript_applied. `manifest` is transient
    (kb-publish deletes it after consumption) and is explicitly excluded from
    existence checks.
    """
    final = outputs.get("final_audio")
    if not final or not Path(final).exists():
        return False

    if intro_music_configured and not bool(outputs.get("intro_applied")):
        return False

    if transcript_enabled:
        if not bool(outputs.get("transcript_applied")):
            return False
        vtt = outputs.get("vtt")
        md = outputs.get("transcript_md")
        if not vtt or not Path(vtt).exists():
            return False
        if not md or not Path(md).exists():
            return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py -v
```

Expected: all tests pass (~17 tests, all green).

If any test fails, re-read both the test and the implementation and fix. Do NOT skip or weaken tests to make them pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/scripts/postproc_hashing.py \
        plugins/kb/skills/kb-notebooklm/scripts/tests/test_postproc_hashing.py
git commit -m "feat(kb-notebooklm): add postproc_hashing helpers + tests

Provides deterministic params_hash / postproc_hash functions and a
postproc_complete predicate the skill will use to decide whether an
existing run can be reused, partially reprocessed, or fully regenerated.
17 unit tests cover hash sensitivity, intent-vs-effective handling, and
the completeness matrix (including transient-manifest exclusion)."
```

---

## Task 3: Implement `assemble_audio.py`

**Goal:** A CLI that takes a raw NotebookLM MP3, an intro music file, and crossfade parameters, and produces a final MP3 via a single ffmpeg `acrossfade` invocation. Emits structured JSON so the skill's background agent can read `final_offset_seconds` directly.

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py`
- Test: `plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py`

- [ ] **Step 1: Write the failing test file**

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py`:

```python
"""Tests for assemble_audio.py — preflight math, ffmpeg argv, JSON shape."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import assemble_audio as A  # noqa: E402


# ------------------------------
# Preflight clamping
# ------------------------------

def test_preflight_no_clamp_needed():
    # 12s file, request 12s + 3s → effective 12s + 3s
    res = A.preflight(intro_duration=12.0, requested_intro_length=12.0, requested_crossfade=3.0)
    assert res.assembly_possible is True
    assert res.effective_intro_length == pytest.approx(12.0)
    assert res.effective_crossfade == pytest.approx(3.0)
    assert res.warnings == []


def test_preflight_clamps_intro_length_to_file_duration():
    # 5s file, request 12s + 3s → effective 5s + min(3, 4.5)=3s
    res = A.preflight(intro_duration=5.0, requested_intro_length=12.0, requested_crossfade=3.0)
    assert res.assembly_possible is True
    assert res.effective_intro_length == pytest.approx(5.0)
    assert res.effective_crossfade == pytest.approx(3.0)
    # Should warn about the clamp.
    assert any("clamp" in w.lower() or "short" in w.lower() for w in res.warnings)


def test_preflight_clamps_crossfade_when_intro_too_short_for_requested_crossfade():
    # 3s file, request 12s + 3s → effective 3s crossfade must clamp below
    # effective_crossfade = min(3, effective_intro_length - 0.5) = min(3, 2.5) = 2.5
    res = A.preflight(intro_duration=3.0, requested_intro_length=12.0, requested_crossfade=3.0)
    assert res.assembly_possible is True
    assert res.effective_intro_length == pytest.approx(3.0)
    assert res.effective_crossfade == pytest.approx(2.5)


def test_preflight_skips_when_intro_below_floor():
    # 1s file is below the 1.5s floor — skip.
    res = A.preflight(intro_duration=1.0, requested_intro_length=12.0, requested_crossfade=3.0)
    assert res.assembly_possible is False
    assert any("too short" in w.lower() or "skip" in w.lower() for w in res.warnings)


def test_preflight_exact_requested_matches_file():
    # 3s file, request 3s + 2s → effective 3s + 2s (crossfade constraint: 2 < 2.5)
    res = A.preflight(intro_duration=3.0, requested_intro_length=3.0, requested_crossfade=2.0)
    assert res.assembly_possible is True
    assert res.effective_intro_length == pytest.approx(3.0)
    assert res.effective_crossfade == pytest.approx(2.0)


# ------------------------------
# ffmpeg argv construction
# ------------------------------

def test_build_ffmpeg_argv_uses_correct_template():
    argv = A.build_ffmpeg_argv(
        intro_path="/tmp/intro.mp3",
        raw_path="/tmp/raw.mp3",
        output_path="/tmp/out.mp3",
        effective_intro_length=12.0,
        effective_crossfade=3.0,
    )
    # argv is a list (shell-safe). Spot-check key elements.
    assert argv[0] == "ffmpeg"
    assert "-y" in argv
    # `-t` comes BEFORE `-i` for the intro to trim it.
    t_idx = argv.index("-t")
    i_idx = argv.index("-i", t_idx)
    assert argv[t_idx + 1] == "12.0"
    assert argv[i_idx + 1] == "/tmp/intro.mp3"
    # Second input is the raw.
    second_i = argv.index("-i", i_idx + 1)
    assert argv[second_i + 1] == "/tmp/raw.mp3"
    # Filter uses acrossfade with d=3.0 and triangular curves.
    filter_idx = argv.index("-filter_complex")
    fc = argv[filter_idx + 1]
    assert "acrossfade=d=3.0" in fc
    assert "c1=tri" in fc
    assert "c2=tri" in fc
    # Map the filter output.
    map_idx = argv.index("-map")
    assert argv[map_idx + 1] == "[a]"
    # MP3 codec and bitrate.
    assert "libmp3lame" in argv
    assert "192k" in argv
    # Output path is last.
    assert argv[-1] == "/tmp/out.mp3"


def test_build_ffmpeg_argv_handles_paths_with_spaces():
    argv = A.build_ffmpeg_argv(
        intro_path="/tmp/My Intro Music.mp3",
        raw_path="/tmp/raw with spaces.mp3",
        output_path="/tmp/out.mp3",
        effective_intro_length=10.0,
        effective_crossfade=2.5,
    )
    # argv is a list, so spaces are preserved as single tokens.
    assert "/tmp/My Intro Music.mp3" in argv
    assert "/tmp/raw with spaces.mp3" in argv


# ------------------------------
# JSON output shape
# ------------------------------

def test_json_success_shape():
    obj = A.build_result_json(
        success=True,
        intro_applied=True,
        output="/tmp/out.mp3",
        duration_seconds=1200.5,
        effective_intro_length=12.0,
        effective_crossfade=3.0,
        warnings=["intro clip shorter than requested, clamped to 12s"],
        error=None,
    )
    assert obj["success"] is True
    assert obj["intro_applied"] is True
    assert obj["output"] == "/tmp/out.mp3"
    assert obj["duration_seconds"] == 1200.5
    assert obj["effective_intro_length"] == 12.0
    assert obj["effective_crossfade"] == 3.0
    assert obj["final_offset_seconds"] == 9.0  # intro - crossfade on success
    assert obj["warnings"] == ["intro clip shorter than requested, clamped to 12s"]
    assert obj["error"] is None


def test_json_failure_shape_has_zero_offset():
    obj = A.build_result_json(
        success=False,
        intro_applied=False,
        output=None,
        duration_seconds=None,
        effective_intro_length=0.0,
        effective_crossfade=0.0,
        warnings=["ffmpeg exited 1: invalid stream"],
        error="ffmpeg failed",
    )
    assert obj["success"] is False
    assert obj["intro_applied"] is False
    # Failure → offset MUST be 0 so VTT aligns to the fallback (raw-as-final).
    assert obj["final_offset_seconds"] == 0.0
    assert obj["error"] == "ffmpeg failed"


# ------------------------------
# ffprobe duration (integration with real ffmpeg)
# ------------------------------

def test_probe_duration_returns_float_seconds(silent_wav):
    d = A.probe_duration(str(silent_wav))
    assert 2.5 <= d <= 3.5  # allow wiggle room for ffmpeg encoding overhead


def test_probe_duration_raises_on_missing_file(tmp_path, ffmpeg_required):
    with pytest.raises(A.ProbeError):
        A.probe_duration(str(tmp_path / "nonexistent.mp3"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py -v
```

Expected: ModuleNotFoundError: No module named 'assemble_audio'.

- [ ] **Step 3: Implement `assemble_audio.py`**

Create `plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py`:

```python
#!/usr/bin/env python3
"""Assemble final podcast MP3 from intro music + raw NotebookLM output.

Thin wrapper around `ffmpeg -filter_complex acrossfade`. Performs preflight
on the intro file (clamping intro_length and crossfade to safe values for
short clips), invokes ffmpeg, and emits a structured JSON status line so
the orchestrating skill can read the final offset as a single source of truth.

Exit codes:
  0  success (intro_applied may still be false if config says so)
  1  ffmpeg failed / preflight determined assembly is not possible
  2  invalid CLI arguments
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


# Minimum intro duration we'll even consider (seconds). Below this, skip.
INTRO_FLOOR_SECONDS = 1.5

# Keep at least this much music-only head before the crossfade starts.
MIN_MUSIC_HEAD_SECONDS = 0.5


class ProbeError(RuntimeError):
    """ffprobe could not determine duration."""


@dataclasses.dataclass
class PreflightResult:
    assembly_possible: bool
    effective_intro_length: float
    effective_crossfade: float
    warnings: list[str]


def preflight(
    *, intro_duration: float, requested_intro_length: float, requested_crossfade: float
) -> PreflightResult:
    """Compute effective intro length and crossfade for a given file duration.

    Contract:
      - effective_intro_length = min(requested_intro_length, intro_duration)
      - effective_crossfade    = min(requested_crossfade, effective_intro_length - MIN_MUSIC_HEAD)
      - assembly_possible = intro_duration >= INTRO_FLOOR
    """
    warnings: list[str] = []

    if intro_duration < INTRO_FLOOR_SECONDS:
        warnings.append(
            f"Intro clip duration {intro_duration:.2f}s is below floor "
            f"{INTRO_FLOOR_SECONDS}s — skipping assembly."
        )
        return PreflightResult(False, 0.0, 0.0, warnings)

    effective_intro_length = min(requested_intro_length, intro_duration)
    if effective_intro_length < requested_intro_length:
        warnings.append(
            f"Intro clip shorter than requested ({intro_duration:.2f}s < "
            f"{requested_intro_length}s) — clamped to {effective_intro_length:.2f}s."
        )

    # Keep at least MIN_MUSIC_HEAD_SECONDS of music-only head before the crossfade.
    max_crossfade = max(0.0, effective_intro_length - MIN_MUSIC_HEAD_SECONDS)
    effective_crossfade = min(requested_crossfade, max_crossfade)
    if effective_crossfade < requested_crossfade:
        warnings.append(
            f"Crossfade clamped from {requested_crossfade}s to "
            f"{effective_crossfade:.2f}s to preserve music-only head."
        )

    return PreflightResult(True, effective_intro_length, effective_crossfade, warnings)


def probe_duration(path: str) -> float:
    """Run `ffprobe` to get the duration of an audio file in seconds."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1",
                path,
            ],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise ProbeError(f"ffprobe not on PATH: {e}") from e
    except subprocess.CalledProcessError as e:
        raise ProbeError(f"ffprobe failed: {e.stderr.strip()}") from e

    text = out.stdout.strip()
    if not text:
        raise ProbeError(f"ffprobe returned empty duration for {path}")
    try:
        return float(text)
    except ValueError as e:
        raise ProbeError(f"ffprobe returned non-numeric duration: {text!r}") from e


def build_ffmpeg_argv(
    *,
    intro_path: str,
    raw_path: str,
    output_path: str,
    effective_intro_length: float,
    effective_crossfade: float,
) -> list[str]:
    """Construct the ffmpeg command as an argv list (no shell injection)."""
    # Format floats to stable string form.
    intro_len_s = f"{effective_intro_length}"
    cf_s = f"{effective_crossfade}"
    filter_str = f"[0:a][1:a]acrossfade=d={cf_s}:c1=tri:c2=tri[a]"
    return [
        "ffmpeg", "-y",
        "-t", intro_len_s, "-i", intro_path,
        "-i", raw_path,
        "-filter_complex", filter_str,
        "-map", "[a]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ]


def run_ffmpeg(argv: list[str]) -> tuple[int, str]:
    """Run ffmpeg, return (returncode, stderr_text)."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError as e:
        return (127, f"ffmpeg not on PATH: {e}")
    return (result.returncode, result.stderr)


def build_result_json(
    *,
    success: bool,
    intro_applied: bool,
    output: str | None,
    duration_seconds: float | None,
    effective_intro_length: float,
    effective_crossfade: float,
    warnings: list[str],
    error: str | None,
) -> dict[str, Any]:
    """Assemble the JSON status object. `final_offset_seconds` is authoritative."""
    final_offset = (effective_intro_length - effective_crossfade) if (success and intro_applied) else 0.0
    return {
        "success": success,
        "intro_applied": intro_applied,
        "output": output,
        "duration_seconds": duration_seconds,
        "effective_intro_length": effective_intro_length,
        "effective_crossfade": effective_crossfade,
        "final_offset_seconds": final_offset,
        "warnings": warnings,
        "error": error,
    }


def _final_duration_after_assembly(*, raw_duration: float, effective_intro_length: float, effective_crossfade: float) -> float:
    """Total output duration of the acrossfade graph."""
    return effective_intro_length + raw_duration - effective_crossfade


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble final podcast MP3 with intro crossfade.")
    parser.add_argument("--raw-audio", required=True, help="Path to raw NotebookLM MP3")
    parser.add_argument("--intro", required=True, help="Path to intro music file")
    parser.add_argument("--output", required=True, help="Path for the assembled MP3")
    parser.add_argument("--intro-length", type=float, default=12.0, help="Target intro length in seconds (default 12)")
    parser.add_argument("--crossfade", type=float, default=3.0, help="Crossfade duration in seconds (default 3)")
    parser.add_argument("--json", action="store_true", help="Emit JSON status to stdout")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    warnings: list[str] = []

    # Probe raw audio duration (used for output duration calculation).
    try:
        raw_duration = probe_duration(args.raw_audio)
    except ProbeError as e:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=None,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=[f"Could not probe raw audio: {e}"],
            error="probe_raw_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    # Probe intro duration.
    try:
        intro_duration = probe_duration(args.intro)
    except ProbeError as e:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=[f"Could not probe intro: {e}"],
            error="probe_intro_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    pre = preflight(
        intro_duration=intro_duration,
        requested_intro_length=args.intro_length,
        requested_crossfade=args.crossfade,
    )
    warnings.extend(pre.warnings)

    if not pre.assembly_possible:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=warnings,
            error="intro_too_short",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    # Ensure output directory exists.
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    argv_ffmpeg = build_ffmpeg_argv(
        intro_path=args.intro,
        raw_path=args.raw_audio,
        output_path=args.output,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
    )
    rc, stderr = run_ffmpeg(argv_ffmpeg)
    if rc != 0:
        warnings.append(f"ffmpeg exited {rc}: {stderr.strip()[:500]}")
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=pre.effective_intro_length,
            effective_crossfade=pre.effective_crossfade,
            warnings=warnings,
            error="ffmpeg_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    total_duration = _final_duration_after_assembly(
        raw_duration=raw_duration,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
    )
    payload = build_result_json(
        success=True, intro_applied=True, output=args.output, duration_seconds=total_duration,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
        warnings=warnings,
        error=None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py -v
```

Expected: all tests pass (~11 tests green, including two that actually shell out to ffmpeg — they skip if ffmpeg is absent).

- [ ] **Step 5: Manual smoke test against real intro music (optional but recommended)**

Run the CLI against a real short clip to confirm end-to-end works. Skip this step in a CI environment — it's for your own confidence.

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i sine=frequency=440:duration=15 /tmp/intro.wav && \
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i sine=frequency=220:duration=30 /tmp/raw.wav && \
  python3 plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py \
    --raw-audio /tmp/raw.wav --intro /tmp/intro.wav \
    --output /tmp/out.mp3 --intro-length 12 --crossfade 3 --json
```

Expected JSON: `{"success": true, "intro_applied": true, "output": "/tmp/out.mp3", "duration_seconds": ~39, "effective_intro_length": 12.0, "effective_crossfade": 3.0, "final_offset_seconds": 9.0, ...}`.

Inspect output file duration via `ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 /tmp/out.mp3` — should be ~39s.

- [ ] **Step 6: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py \
        plugins/kb/skills/kb-notebooklm/scripts/tests/test_assemble_audio.py
git commit -m "feat(kb-notebooklm): add assemble_audio.py with ffmpeg crossfade

New script that prepends intro music to raw NotebookLM MP3 using
'ffmpeg -filter_complex acrossfade'. Preflight clamps intro length
and crossfade for short intro files; structured JSON output exposes
final_offset_seconds as the single source of truth for transcription.

Tests (11): preflight math for 4 clip/config combinations, ffmpeg argv
construction with Unicode-safe path handling, JSON success/failure
shapes, ffprobe integration (skipped if ffmpeg absent)."
```

---

## Task 4: Implement `transcribe_audio.py`

**Goal:** A CLI that takes a raw NotebookLM MP3 plus host names, runs faster-whisper for transcription and pyannote for diarization, aligns words to speakers (splitting at diarization boundaries), applies the host-name mapping with self-intro validation, and emits a WebVTT file (offset-shifted to align to the final MP3) and a markdown transcript.

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py`
- Test: `plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py`

- [ ] **Step 1: Write the failing test file**

Create `plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py`:

```python
"""Tests for transcribe_audio.py — timestamp formatting, VTT escaping, speaker labeling."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import transcribe_audio as T  # noqa: E402


# ------------------------------
# Timestamp formatting
# ------------------------------

def test_format_timestamp_zero():
    assert T.format_timestamp(0.0) == "00:00:00.000"


def test_format_timestamp_sub_second():
    assert T.format_timestamp(0.24) == "00:00:00.240"


def test_format_timestamp_seconds():
    assert T.format_timestamp(65.5) == "00:01:05.500"


def test_format_timestamp_crosses_hour():
    assert T.format_timestamp(3609.1) == "01:00:09.100"


def test_format_timestamp_applies_offset():
    assert T.format_timestamp(0.24, offset=9.0) == "00:00:09.240"


def test_format_timestamp_applies_offset_crossing_minute():
    assert T.format_timestamp(55.5, offset=9.0) == "00:01:04.500"


# ------------------------------
# VTT escaping
# ------------------------------

def test_vtt_escape_lt_gt_amp():
    assert T.escape_vtt_text("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_vtt_escape_preserves_cjk():
    # No special characters in CJK — pass through.
    assert T.escape_vtt_text("瓜瓜龙你好") == "瓜瓜龙你好"


def test_vtt_voice_tag_escapes_angle_brackets_in_speaker_name():
    # Defensive: if a speaker name somehow contains <, it must not break the voice tag.
    assert T.voice_tag("Weird<Name>", "hello") == "<v Weird&lt;Name&gt;>hello"


def test_vtt_voice_tag_normal_case():
    assert T.voice_tag("瓜瓜龙", "大家好") == "<v 瓜瓜龙>大家好"


# ------------------------------
# Align words to speakers
# ------------------------------

def test_align_words_single_speaker(fake_whisper_segment, fake_diarization_turn):
    seg = fake_whisper_segment(0.0, 4.0, "hello world how are you")
    turns = [fake_diarization_turn(0.0, 4.0, "SPEAKER_00")]
    subs = T.split_segment_by_diarization(seg, turns)
    # All words in one speaker → one sub-segment.
    assert len(subs) == 1
    assert subs[0]["speaker"] == "SPEAKER_00"
    assert subs[0]["text"].startswith("hello")
    assert subs[0]["start"] == pytest.approx(0.0, abs=0.01)
    assert subs[0]["end"] == pytest.approx(4.0, abs=0.01)


def test_align_words_splits_at_diarization_boundary(fake_whisper_segment, fake_diarization_turn):
    """A single whisper segment whose words span two turns must split into two subs."""
    seg = fake_whisper_segment(0.0, 4.0, "hello world how are you")
    # Turn boundary at 2.0: SPEAKER_00 [0..2], SPEAKER_01 [2..4].
    turns = [
        fake_diarization_turn(0.0, 2.0, "SPEAKER_00"),
        fake_diarization_turn(2.0, 4.0, "SPEAKER_01"),
    ]
    subs = T.split_segment_by_diarization(seg, turns)
    assert len(subs) == 2
    assert subs[0]["speaker"] == "SPEAKER_00"
    assert subs[1]["speaker"] == "SPEAKER_01"
    # Words split: "hello world" went to first, "how are you" to second.
    assert "hello" in subs[0]["text"]
    assert "how" in subs[1]["text"]


def test_align_words_assigns_uncovered_words_to_most_recent_speaker(fake_whisper_segment, fake_diarization_turn):
    """If the diarization turn ends before the segment does, trailing words go to the most recent speaker."""
    seg = fake_whisper_segment(0.0, 4.0, "hello world silence tail")
    turns = [fake_diarization_turn(0.0, 2.0, "SPEAKER_00")]  # no coverage for 2..4
    subs = T.split_segment_by_diarization(seg, turns)
    assert len(subs) >= 1
    # All words still get labeled — trailing assigned to SPEAKER_00 (the last known speaker).
    speakers = {sub["speaker"] for sub in subs}
    assert speakers == {"SPEAKER_00"}


# ------------------------------
# Host-pool mapping (first-appearance ordering)
# ------------------------------

def test_map_speakers_to_hosts_by_first_appearance():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01", "text": "hi"},
        {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "hello"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_01", "text": "there"},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    # SPEAKER_01 appeared first → 瓜瓜龙, SPEAKER_00 → 海发菜
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert mapped[2]["speaker"] == "瓜瓜龙"


def test_map_speakers_overflow_synthesizes_guest_names():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "A", "text": "a"},
        {"start": 1.0, "end": 2.0, "speaker": "B", "text": "b"},
        {"start": 2.0, "end": 3.0, "speaker": "C", "text": "c"},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]  # pool exhausted at speaker 3
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert mapped[2]["speaker"] == "嘉宾A"


def test_self_intro_swap_triggers_when_ordering_is_wrong():
    """If speaker_00's first line says '我是海发菜' (not 瓜瓜龙), swap the mapping."""
    subs = [
        # Fake data: the speaker that appears first is SAYING the other host's name.
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "我是海发菜, 欢迎收听."},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "我是瓜瓜龙, 今天要聊 KV Cache."},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    # After swap: SPEAKER_00 → 海发菜 (because it says "我是海发菜")
    assert mapped[0]["speaker"] == "海发菜"
    assert mapped[1]["speaker"] == "瓜瓜龙"
    assert any("swap" in w.lower() for w in warnings)


def test_self_intro_does_not_swap_when_ordering_is_correct():
    subs = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "我是瓜瓜龙, 欢迎收听."},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "我是海发菜, 今天我们聊."},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert not any("swap" in w.lower() for w in warnings)


# ------------------------------
# Render outputs
# ------------------------------

def test_render_vtt_zero_offset():
    subs = [
        {"start": 0.24, "end": 4.12, "speaker": "瓜瓜龙", "text": "大家好."},
        {"start": 4.12, "end": 9.56, "speaker": "海发菜", "text": "今天聊 KV Cache."},
    ]
    vtt = T.render_vtt(subs, offset=0.0)
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:00.240 --> 00:00:04.120" in vtt
    assert "<v 瓜瓜龙>大家好." in vtt
    assert "00:00:04.120 --> 00:00:09.560" in vtt
    assert "<v 海发菜>今天聊 KV Cache." in vtt


def test_render_vtt_with_offset():
    subs = [{"start": 0.24, "end": 4.12, "speaker": "瓜瓜龙", "text": "大家好."}]
    vtt = T.render_vtt(subs, offset=9.0)
    assert "00:00:09.240 --> 00:00:13.120" in vtt


def test_render_markdown_merges_consecutive_same_speaker():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "瓜瓜龙", "text": "大家好."},
        {"start": 1.0, "end": 2.0, "speaker": "瓜瓜龙", "text": "今天聊 KV Cache."},
        {"start": 2.0, "end": 3.0, "speaker": "海发菜", "text": "好的."},
    ]
    md = T.render_markdown(subs, title="全栈AI — KV Cache (2026-04-20)")
    assert md.startswith("# 全栈AI — KV Cache (2026-04-20)\n")
    # Consecutive 瓜瓜龙 segments merged with a space.
    assert "**瓜瓜龙:** 大家好. 今天聊 KV Cache." in md
    # Speaker change → new paragraph.
    assert "**海发菜:** 好的." in md


def test_derive_title_from_filename():
    assert T.derive_title("podcast-kv-cache-2026-04-20.raw.mp3") == "全栈AI — kv-cache (2026-04-20)"
    assert T.derive_title("podcast-attention-2026-05-12.mp3") == "全栈AI — attention (2026-05-12)"


def test_derive_title_falls_back_to_basename_when_pattern_mismatched():
    # Unrecognized pattern → fall back to cleanup-only.
    assert T.derive_title("strange-name.wav").startswith("全栈AI — ")


# ------------------------------
# JSON output shape
# ------------------------------

def test_json_success_shape():
    obj = T.build_result_json(
        success=True, vtt="/tmp/x.vtt", markdown="/tmp/x.md",
        speaker_count=2, duration_seconds=1200.5,
        warnings=[], error=None,
    )
    assert obj["success"] is True
    assert obj["vtt"] == "/tmp/x.vtt"
    assert obj["markdown"] == "/tmp/x.md"
    assert obj["speaker_count"] == 2
    assert obj["error"] is None


def test_json_failure_shape():
    obj = T.build_result_json(
        success=False, vtt=None, markdown=None,
        speaker_count=0, duration_seconds=None,
        warnings=["HUGGINGFACE_TOKEN not set"],
        error="missing_hf_token",
    )
    assert obj["success"] is False
    assert obj["vtt"] is None
    assert obj["error"] == "missing_hf_token"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py -v
```

Expected: ModuleNotFoundError: No module named 'transcribe_audio'.

- [ ] **Step 3: Implement `transcribe_audio.py`**

Create `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py`:

```python
#!/usr/bin/env python3
"""Transcribe a raw NotebookLM MP3 with faster-whisper + pyannote speaker diarization.

Emits WebVTT (with optional offset so captions align to the final assembled MP3)
and a human-readable markdown transcript.

Exit codes:
  0  success (also emitted when diarization produced only 1 cluster — logged)
  1  invalid CLI arguments
  3  HUGGINGFACE_TOKEN env var missing
  4  model download failed (offline or HF auth issues)
  5  whisper/pyannote runtime error
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Sequence


# ------------------------------
# Pure helpers (no ML deps — safe to import for tests)
# ------------------------------

def format_timestamp(seconds: float, offset: float = 0.0) -> str:
    """Format a timestamp as HH:MM:SS.mmm (WebVTT form)."""
    t = max(0.0, seconds + offset)
    total_ms = int(round(t * 1000))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def escape_vtt_text(text: str) -> str:
    """Minimal HTML/WebVTT escaping — escape & first, then < and >."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def voice_tag(speaker: str, text: str) -> str:
    """Wrap cue body in a WebVTT voice tag. Escapes speaker name defensively."""
    return f"<v {escape_vtt_text(speaker)}>{escape_vtt_text(text)}"


def split_segment_by_diarization(
    segment: dict[str, Any], turns: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Split a whisper segment's words into sub-segments by speaker.

    For each word, look up the diarization turn whose interval covers the word's
    midpoint. Words with no covering turn inherit the most recently seen speaker.
    Consecutive words with the same speaker are merged into one sub-segment.
    """
    words = segment.get("words") or []
    if not words:
        return []

    def _speaker_for_time(t: float, last_speaker: str | None) -> str | None:
        for turn in turns:
            if turn["start"] <= t <= turn["end"]:
                return turn["speaker"]
        return last_speaker

    last_speaker: str | None = None
    # Bootstrap last_speaker: if the first word's midpoint lands in a turn, great.
    # Otherwise fall back to the first turn's speaker if any.
    if turns:
        last_speaker = turns[0]["speaker"]

    subs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for w in words:
        midpoint = (w["start"] + w["end"]) / 2.0
        sp = _speaker_for_time(midpoint, last_speaker)
        if sp is None:
            sp = last_speaker or "SPEAKER_00"
        last_speaker = sp

        if current is None or current["speaker"] != sp:
            if current is not None:
                subs.append(current)
            current = {
                "start": w["start"],
                "end": w["end"],
                "speaker": sp,
                "text": w["word"].strip(),
            }
        else:
            current["end"] = w["end"]
            # Space-separate tokens. strip() removes leading space from faster-whisper's
            # raw word forms (they typically start with a space).
            current["text"] = (current["text"] + " " + w["word"].strip()).strip()

    if current is not None:
        subs.append(current)

    # Clean doubled spaces from naive joining.
    for s in subs:
        s["text"] = re.sub(r"\s+", " ", s["text"]).strip()

    return subs


def map_speakers_to_hosts(
    sub_segments: Sequence[dict[str, Any]], host_pool: Sequence[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Assign host names to speaker IDs by first-appearance order.

    Applies a best-effort self-intro swap: if the speaker that appears first
    introduces the OTHER host's name (and not its own), swap the mapping.
    Overflow speakers beyond the host pool get synthesized 嘉宾A/B/C labels.
    """
    warnings: list[str] = []
    # First-appearance order of distinct speaker IDs.
    seen: list[str] = []
    for sub in sub_segments:
        sp = sub["speaker"]
        if sp not in seen:
            seen.append(sp)

    # Build initial mapping.
    mapping: dict[str, str] = {}
    for i, sp in enumerate(seen):
        if i < len(host_pool):
            mapping[sp] = host_pool[i]
        else:
            guest_idx = i - len(host_pool)
            mapping[sp] = f"嘉宾{chr(ord('A') + guest_idx)}"

    # Self-intro validation (only makes sense when we have at least 2 hosts and 2 speakers).
    if len(host_pool) >= 2 and len(seen) >= 2:
        def _first_text(speaker_id: str) -> str:
            for s in sub_segments:
                if s["speaker"] == speaker_id:
                    return s["text"]
            return ""

        first_sp = seen[0]
        second_sp = seen[1]
        first_text = _first_text(first_sp)
        second_text = _first_text(second_sp)
        h0, h1 = host_pool[0], host_pool[1]
        # Swap if first speaker says h1 but not h0, AND second speaker says h0 but not h1.
        if (h1 in first_text and h0 not in first_text and
                h0 in second_text and h1 not in second_text):
            mapping[first_sp] = h1
            mapping[second_sp] = h0
            warnings.append(
                f"Self-intro swap: speaker order did not match host pool; "
                f"swapped to {h1}, {h0}."
            )

    mapped = [
        {**sub, "speaker": mapping[sub["speaker"]]}
        for sub in sub_segments
    ]
    return mapped, warnings


def render_vtt(sub_segments: Sequence[dict[str, Any]], offset: float = 0.0) -> str:
    """Render sub-segments as WebVTT text."""
    lines = ["WEBVTT", ""]
    for s in sub_segments:
        start = format_timestamp(s["start"], offset=offset)
        end = format_timestamp(s["end"], offset=offset)
        lines.append(f"{start} --> {end}")
        lines.append(voice_tag(s["speaker"], s["text"]))
        lines.append("")
    return "\n".join(lines)


def render_markdown(sub_segments: Sequence[dict[str, Any]], title: str) -> str:
    """Render sub-segments as markdown, merging consecutive same-speaker turns."""
    paragraphs: list[tuple[str, str]] = []
    for s in sub_segments:
        sp = s["speaker"]
        text = s["text"]
        if paragraphs and paragraphs[-1][0] == sp:
            prev_sp, prev_text = paragraphs[-1]
            paragraphs[-1] = (prev_sp, (prev_text + " " + text).strip())
        else:
            paragraphs.append((sp, text))

    body = "\n\n".join(f"**{sp}:** {text}" for sp, text in paragraphs)
    return f"# {title}\n\n{body}\n"


_FILENAME_PATTERN = re.compile(r"^podcast-(?P<theme>.+)-(?P<date>\d{4}-\d{2}-\d{2})(?:\.raw)?\.(?:mp3|wav|m4a|flac)$", re.IGNORECASE)


def derive_title(filename: str) -> str:
    """Derive an H1 title from a raw audio filename, following the '全栈AI — <theme> (date)' convention."""
    m = _FILENAME_PATTERN.match(Path(filename).name)
    if m:
        return f"全栈AI — {m.group('theme')} ({m.group('date')})"
    # Fallback: strip common suffixes, prefix brand.
    stem = Path(filename).stem
    stem = re.sub(r"\.raw$", "", stem, flags=re.IGNORECASE)
    return f"全栈AI — {stem}"


def build_result_json(
    *,
    success: bool,
    vtt: str | None,
    markdown: str | None,
    speaker_count: int,
    duration_seconds: float | None,
    warnings: list[str],
    error: str | None,
) -> dict[str, Any]:
    return {
        "success": success,
        "vtt": vtt,
        "markdown": markdown,
        "speaker_count": speaker_count,
        "duration_seconds": duration_seconds,
        "warnings": warnings,
        "error": error,
    }


# ------------------------------
# Model-loading seams (integration boundary — stubbed in tests)
# ------------------------------

def resolve_device(requested: str) -> str:
    """Pick a device for faster-whisper.

    `mps` is intentionally NOT offered — faster-whisper doesn't support it.
    Apple Silicon and Intel Macs both run on cpu.
    """
    if requested in ("cpu", "cuda"):
        return requested
    # auto
    if platform.system() == "Darwin":
        return "cpu"
    # On Linux/NVIDIA, best-effort detect CUDA.
    try:
        import ctranslate2  # type: ignore
        if getattr(ctranslate2, "get_cuda_device_count", lambda: 0)() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def transcribe_with_whisper(
    audio_path: str, *, model_name: str, device: str, language: str
) -> tuple[list[dict[str, Any]], float]:
    """Run faster-whisper and return (segments, duration_seconds)."""
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_name, device=device, compute_type="auto")
    segments, info = model.transcribe(
        audio_path, language=language, word_timestamps=True, vad_filter=True,
    )
    out: list[dict[str, Any]] = []
    for s in segments:
        words = [
            {"start": w.start, "end": w.end, "word": w.word}
            for w in (s.words or [])
        ]
        out.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
    return out, float(info.duration)


def diarize_with_pyannote(audio_path: str, *, hf_token: str) -> list[dict[str, Any]]:
    """Run pyannote speaker-diarization-3.1 and return turns."""
    from pyannote.audio import Pipeline  # type: ignore

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    diarization = pipeline(audio_path, num_speakers=2)
    return [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(label)}
        for turn, _, label in diarization.itertracks(yield_label=True)
    ]


# ------------------------------
# CLI
# ------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe + diarize a raw podcast MP3.")
    parser.add_argument("--audio", required=True, help="Path to raw NotebookLM MP3")
    parser.add_argument("--hosts", required=True, help="JSON array of host names, longest pool first")
    parser.add_argument("--output-vtt", required=True, help="Path for WebVTT output")
    parser.add_argument("--output-md", required=True, help="Path for markdown output")
    parser.add_argument("--vtt-offset-seconds", type=float, default=0.0,
                        help="Offset added to all VTT timestamps so captions align to the FINAL MP3.")
    parser.add_argument("--model", default="large-v3", help="faster-whisper model name")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                        help="Inference device (mps not supported)")
    parser.add_argument("--language", default="zh", help="Whisper language hint")
    parser.add_argument("--title", default=None, help="Optional H1 title (else derived from filename)")
    parser.add_argument("--json", action="store_true", help="Emit JSON status to stdout")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    warnings: list[str] = []

    try:
        host_pool = json.loads(args.hosts)
        if not isinstance(host_pool, list) or len(host_pool) < 1:
            raise ValueError("hosts must be a non-empty JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"invalid --hosts: {e}"], error="invalid_hosts",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    hf_token = os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if not hf_token:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=["HUGGINGFACE_TOKEN env var not set. Pyannote requires license acceptance + token — see kb-init setup."],
            error="missing_hf_token",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 3

    device = resolve_device(args.device)

    # Stage 1: transcription
    try:
        whisper_segments, duration = transcribe_with_whisper(
            args.audio, model_name=args.model, device=device, language=args.language,
        )
    except (ImportError, ModuleNotFoundError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"faster-whisper not installed: {e}"], error="module_missing",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 4
    except Exception as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"whisper transcription failed: {type(e).__name__}: {e}"], error="whisper_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 5

    # Stage 2: diarization
    try:
        turns = diarize_with_pyannote(args.audio, hf_token=hf_token)
    except (ImportError, ModuleNotFoundError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=duration,
            warnings=[f"pyannote.audio not installed: {e}"], error="module_missing",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 4
    except Exception as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=duration,
            warnings=[f"pyannote diarization failed: {type(e).__name__}: {e}"], error="pyannote_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 5

    if not turns:
        warnings.append("Diarization produced no turns — labeling as single speaker.")
        turns = [{"start": 0.0, "end": duration, "speaker": "SPEAKER_00"}]

    # Stage 3: alignment + labeling
    subs: list[dict[str, Any]] = []
    for seg in whisper_segments:
        subs.extend(split_segment_by_diarization(seg, turns))

    mapped, map_warnings = map_speakers_to_hosts(subs, host_pool)
    warnings.extend(map_warnings)

    speaker_count = len({s["speaker"] for s in mapped})
    if speaker_count == 1:
        warnings.append("Only 1 distinct speaker after mapping — diarization may have failed.")

    # Stage 4: render + write
    vtt_text = render_vtt(mapped, offset=args.vtt_offset_seconds)
    title = args.title or derive_title(args.audio)
    md_text = render_markdown(mapped, title=title)

    Path(args.output_vtt).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_vtt).write_text(vtt_text, encoding="utf-8")
    Path(args.output_md).write_text(md_text, encoding="utf-8")

    payload = build_result_json(
        success=True, vtt=args.output_vtt, markdown=args.output_md,
        speaker_count=speaker_count, duration_seconds=duration,
        warnings=warnings, error=None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py -v
```

Expected: all tests pass (~24 tests green).

Note: the tests do NOT exercise `transcribe_with_whisper` or `diarize_with_pyannote` — those functions require real ML models. They're covered by the procedural end-to-end tests in the spec.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py \
        plugins/kb/skills/kb-notebooklm/scripts/tests/test_transcribe_audio.py
git commit -m "feat(kb-notebooklm): add transcribe_audio.py with whisper + pyannote

Runs faster-whisper on raw NotebookLM audio, diarizes with pyannote,
splits whisper segments at diarization boundaries using word timestamps,
maps pyannote speaker IDs to host pool by first-appearance order (with
self-intro swap for misordered introductions), and emits WebVTT
(offset-aware) + merged-paragraph markdown.

Tests (24): timestamp formatting, VTT escaping, voice tag safety,
word-level speaker splitting including cross-boundary segments,
first-appearance host mapping, pool-overflow 嘉宾A/B/C fallback,
self-intro swap logic, markdown paragraph merging, title derivation,
JSON success/failure shapes."
```

---

## Task 5: Update `prompts/podcast-tutor.md` — brand fix + host intro

**Goal:** Fix the "My Lessons Learned" brand leak to 全栈AI, add a `{hosts}` placeholder, and insert an explicit HOST INTRODUCTION section. The prompt template uses `{host0}` / `{host1}` placeholders consistent with existing `{series_context}` / `{lesson_list}` conventions — the skill substitutes them at render time in Task 6.

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md`

- [ ] **Step 1: Read the current prompt to confirm starting state**

Run:

```bash
cat plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md
```

Confirm line 3 starts with `This is an episode of "My Lessons Learned"` — this is what we're replacing.

- [ ] **Step 2: Apply the brand fix**

Use Edit to change line 3:

- Old string: `This is an episode of "My Lessons Learned" — a technical podcast where two hosts break down AI/ML concepts for engineers who want to go deeper.`
- New string: `This is an episode of 全栈AI — a technical podcast where two hosts break down AI/ML concepts for engineers who want to go deeper.`

- [ ] **Step 3: Insert the `{hosts}` placeholder block**

Use Edit to add the block between `{series_context}` (line 1) and the description line (now on line 3 post-edit).

- Old string: `{series_context}\n\nThis is an episode of 全栈AI`
- New string:
  ```
  {series_context}

  {hosts}

  This is an episode of 全栈AI
  ```

- [ ] **Step 4: Insert the HOST INTRODUCTION section between OPENING and EPISODE FLOW**

Use Edit. Find the existing `OPENING:` block. The current structure is:

```
OPENING:
Start with a brief, natural greeting. [...]

EPISODE FLOW:
[...]
```

Apply this edit:

- Old string:
  ```
  OPENING:
  Start with a brief, natural greeting. Hook the listener by picking the most surprising or counterintuitive insight from today's topic and leading with it — something like "Did you know that [unexpected fact from the source material]?" or "So I was reading about [topic] and there's this thing that most people get completely wrong..." Do NOT reference external news events that aren't in the source material. Keep it short — just enough to spark curiosity, then state what the episode's single main topic is and why it matters.

  EPISODE FLOW:
  ```
- New string:
  ```
  HOST INTRODUCTION (first 10-15 seconds of dialogue):
  Open with a warm, natural self-introduction. Example shape:
    {host0}: "Hi 大家好, 欢迎收听全栈AI, 我是{host0}."
    {host1}: "我是{host1}. 今天我们要聊的是..."
  Keep it brief — one or two exchanges. Then flow directly into the hook described in OPENING.
  Throughout the episode, the hosts address each other by name at natural moments ("{host1} 你刚才说...", "{host0} 那这个和 X 有什么关系?").

  OPENING:
  Start with a brief, natural greeting. Hook the listener by picking the most surprising or counterintuitive insight from today's topic and leading with it — something like "Did you know that [unexpected fact from the source material]?" or "So I was reading about [topic] and there's this thing that most people get completely wrong..." Do NOT reference external news events that aren't in the source material. Keep it short — just enough to spark curiosity, then state what the episode's single main topic is and why it matters.

  EPISODE FLOW:
  ```

- [ ] **Step 5: Verify the final prompt shape**

Run:

```bash
head -20 plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md
```

Confirm:
- Line 1: `{series_context}`
- Line 3: `{hosts}`
- Line 5 (or near): `This is an episode of 全栈AI —`
- HOST INTRODUCTION block appears before OPENING
- No remaining occurrences of "My Lessons Learned"

Final sanity check:

```bash
grep -n "My Lessons Learned\|{hosts}\|{host0}\|{host1}\|HOST INTRODUCTION\|全栈AI" plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md
```

Expected output includes `{hosts}`, `{host0}`, `{host1}`, `HOST INTRODUCTION`, `全栈AI` lines. NO `My Lessons Learned` lines.

- [ ] **Step 6: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md
git commit -m "feat(kb-notebooklm): brand fix (全栈AI) + host introduction in prompt

Replaces 'My Lessons Learned' with 全栈AI (the on-air brand) in the
podcast prompt, adds a {hosts} placeholder consistent with existing
{series_context}/{lesson_list} conventions, and inserts a HOST
INTRODUCTION section instructing the hosts to introduce themselves
by name at the top of every episode. The skill renders {host0}/{host1}
at runtime."
```

---

## Task 6: Update `kb-notebooklm/SKILL.md` — wire in the new scripts and dedup

**Goal:** Reorder the podcast workflow so prompt rendering happens before hashing, introduce `postproc_hash` and the `postproc_complete` predicate, extend the background agent prompt to call `assemble_audio.py` then `transcribe_audio.py` with the actual offset, add the new sidecar fields, and update the cleanup workflow to delete `raw_audio` files when pruning records.

This task edits prose (SKILL.md), so there are no unit tests — verification is by re-reading the edited sections for internal consistency against the spec.

**Files:**
- Modify: `plugins/kb/skills/kb-notebooklm/SKILL.md`

- [ ] **Step 1: Add new kb.yaml config keys to the "Common Preamble (Prerequisites)" section reference**

Use Edit to extend the preamble's kb.yaml reading step (around line 34-35). Find the existing text:

- Old string:
  ```
  1. **Read configuration:**
     Read `kb.yaml`. Check for `integrations.notebooklm` section. If missing or `enabled: false`, report: "NotebookLM integration not enabled in kb.yaml." and STOP.
  ```
- New string:
  ```
  1. **Read configuration:**
     Read `kb.yaml`. Check for `integrations.notebooklm` section. If missing or `enabled: false`, report: "NotebookLM integration not enabled in kb.yaml." and STOP.

     For podcast workflows, also read `integrations.notebooklm.podcast` — new keys supported:
     - `intro_music`: path to the intro music file (null/missing → no intro music).
     - `intro_music_length_seconds` (default 12)
     - `intro_crossfade_seconds` (default 3)
     - `hosts` (default `["瓜瓜龙", "海发菜"]`)
     - `extra_host_names` (default `[]`)
     - `transcript.enabled` (default `false` when absent — set explicitly by `kb-init`)
     - `transcript.model` (default `large-v3`), `transcript.device` (default `auto`), `transcript.language` (default `zh`)
  ```

- [ ] **Step 2: Rewrite the Podcast Workflow algorithm (step 6) with the new ordering**

The current algorithm has steps 6a through 6k. We need to insert 6a' (prompt rendering) and 6b' (hashing with new composition), and rewrite 6c (dedup) and 6k (background agent). Find the section header `### Podcast Workflow` (around line 412) and inside it, find the existing numbered steps.

Apply this edit:

- Old string (step 6a):
  ```
  6a. **Limit:** Truncate to `config.max_sources_per_notebook` (default 45) per episode.

  6b. **Compute hashes:** Calculate `sources_hash` (from file paths and mtimes) and `params_hash` (from format, length, language, instruction template).

  6c. **Dedup check:** Search `state.runs` for matching `workflow + sources_hash + params_hash`. If match found, follow deduplication algorithm (session recovery, skip, re-download, or partial retry). Otherwise continue.
  ```

- New string:
  ```
  6a. **Limit:** Truncate to `config.max_sources_per_notebook` (default 45) per episode.

  6a'. **Resolve host pool and render prompt (NEW):**
       1. Read `integrations.notebooklm.podcast.hosts` from kb.yaml. Default `["瓜瓜龙", "海发菜"]` if missing.
       2. Read `integrations.notebooklm.podcast.extra_host_names`. Default `[]`.
       3. Build `host_pool = hosts + extra_host_names`. Validate len >= 2; if not, abort with clear error.
       4. Read `prompts/podcast-tutor.md`.
       5. Substitute `{series_context}` (compile from published episodes registry — existing logic).
       6. Substitute `{hosts}` with the rendered HOSTS block (see below).
       7. Substitute `{host0}` with `host_pool[0]` and `{host1}` with `host_pool[1]` throughout the template.
       8. Substitute `{lesson_list}` with the episode's lesson list — existing logic.
       9. Store the final string as `rendered_prompt`. This is the exact string that will be sent to `notebooklm generate audio` in step 6i.

       **`{hosts}` block template:**
       ```
       HOSTS:
       This episode has two hosts: {host0} and {host1}.
       They address each other and refer to themselves by these names throughout the episode.
       {host0} typically drives explanations; {host1} asks the sharp follow-up questions. Either host may take either role — keep it natural, not rigid.
       ```
       (with `{host0}` / `{host1}` substituted after this block is inserted.)

  6a''. **Resolve post-processing config (NEW):**
        1. If `intro_music` is set and the file exists: run `ffprobe` to get duration, then compute `effective_intro_length = min(requested_intro_length, duration)` and `effective_crossfade = min(requested_crossfade, effective_intro_length - 0.5)`. Also compute `intro_music_size`, `intro_music_mtime`, and `intro_music_content_sha256` (SHA-256 of file bytes). Set `intro_music_configured = true`.
        2. If `intro_music` is unset, null, or missing on disk: set all intro-related values to empty/zero, `intro_music_configured = false`.
        3. `transcript_enabled = bool(integrations.notebooklm.podcast.transcript.enabled)` (treats absent as false).
        4. `desired_vtt_offset = effective_intro_length - effective_crossfade` (or 0 when intro not configured).

  6b. **Compute `sources_hash`:** Existing logic (file paths + mtimes).

  6b'. **Compute `params_hash` and `postproc_hash` (REVISED):**
        Shell out to `python3 <skill_dir>/scripts/postproc_hashing.py`:
        ```
        python3 -c "
        import sys, json
        sys.path.insert(0, '<skill_dir>/scripts')
        import postproc_hashing as H
        print(json.dumps({
            'params': H.params_hash(
                format=<format>, length=<length>, language=<language>,
                rendered_prompt=<rendered_prompt>, host_pool=<host_pool>[:2],
            ),
            'postproc': H.postproc_hash(
                intro_music_path=<intro_music>, intro_music_mtime=<mtime>,
                intro_music_size=<size>, intro_music_content_sha256=<sha256>,
                requested_intro_length=<requested_intro_length>,
                requested_crossfade_seconds=<requested_crossfade>,
                effective_intro_length=<effective_intro_length>,
                effective_crossfade=<effective_crossfade>,
                transcript_enabled=<transcript_enabled>,
                transcript_model=<transcript.model>,
                transcript_language=<transcript.language>,
                host_pool=<host_pool>,
            ),
        }))
        "
        ```
        Use argv / stdin JSON to avoid shell-quoting the rendered_prompt. (Example: pipe a JSON blob into a python -c that reads stdin.)

  6c. **Dedup check (REVISED):**
      1. Search `state.runs` for matching `workflow + sources_hash + params_hash`.
      2. If match found with all artifacts `completed`:
         - Read `podcast_outputs` from the matched run (or infer `final_audio = artifacts[0].output_files[0]` for pre-migration records, with raw assumed absent).
         - Call the `postproc_complete` helper:
           ```
           python3 -c "
           import sys
           sys.path.insert(0, '<skill_dir>/scripts')
           import postproc_hashing as H
           outputs = {...}  # from run record
           print(H.postproc_complete(outputs, intro_music_configured=<bool>, transcript_enabled=<bool>))
           "
           ```
         - If stored `postproc_hash` matches current AND `postproc_complete` returns True: **skip entirely**. Report skipped episode.
         - Else if stored raw_audio file exists on disk: **re-run post-processing only** (jump to step 6k with `skip_generation=true`). Log "Reusing retained raw audio; re-running post-processing."
         - Else: **fall back to full regeneration**. Log "Raw audio missing — regenerating from NotebookLM."
      3. If any artifact `pending`: session recovery (existing).
      4. If any artifact `failed`: partial retry (existing).
      5. No match: proceed to full generation.
  ```

- [ ] **Step 3: Rewrite step 6i to use the pre-rendered prompt**

Find the existing step 6i (around line 482). Apply this edit:

- Old string:
  ```
  6i. **Generate audio:** Run `source <venv> && notebooklm generate audio "<instructions>" --format <config.podcast.format> --length <config.podcast.length> --language <config.language> --notebook <notebook_id> --json`.

      **Audio instructions template:**

      Read the prompt from `prompts/podcast-tutor.md` relative to this skill's directory.

      **Series bible injection:** If the episode registry exists and contains published
      episodes, compile the series bible (see "Episode Continuity" section) and replace
      the `{series_context}` placeholder in the prompt. If no registry or no published
      episodes, replace `{series_context}` with an empty string.

      **Lesson list injection:** Replace the `{lesson_list}` placeholder with:
      "This episode's main topic: [episode theme name]. Cover these lessons as
      different facets of this single topic: [comma-separated lesson titles].
      Weave them into a unified narrative — build from foundational to advanced
      within this theme. Show how each lesson connects to and deepens the others."

      If the prompt file cannot be found, use this fallback:
      ```
      This episode's main topic: [episode theme name]. Cover these lessons as different facets of this single topic: [comma-separated lesson titles]. Weave them into a unified narrative that builds from foundational to advanced. Make it engaging and educational. Target audience: someone learning ML/AI concepts.
      ```
  ```

- New string:
  ```
  6i. **Generate audio (REVISED):** The prompt has already been fully rendered in step 6a'.
      Invoke:
      ```
      source <venv> && notebooklm generate audio "<rendered_prompt>" \
        --format <config.podcast.format> \
        --length <config.podcast.length> \
        --language <config.language> \
        --notebook <notebook_id> \
        --json
      ```
      Use argv (subprocess list form) or stdin to pass the rendered prompt — it contains
      newlines and CJK text that must survive shell interpolation. If the prompt is
      particularly long, write it to `<staging_dir>/prompt.txt` and use `--prompt-file`
      if the CLI supports it, or read via process substitution.

      If the prompt file cannot be found, use this fallback (same as before):
      ```
      This episode's main topic: [episode theme name]. Cover these lessons as different facets of this single topic: [comma-separated lesson titles]. Weave them into a unified narrative that builds from foundational to advanced. Make it engaging and educational. Target audience: someone learning ML/AI concepts.
      ```
  ```

- [ ] **Step 4: Rewrite step 6k (background agent) with assemble-then-transcribe**

Find the existing step 6k (around line 506). Apply this edit:

- Old string:
  ```
  6k. **Spawn background agent:** Use Agent tool with `run_in_background: true` to wait and download:
      ```
      Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download.
      1. Run: source <venv>/bin/activate && notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
      2. If exit code 0: Run: source <venv>/bin/activate && notebooklm download audio <output_path>/<filename> -n <notebook_id>
      3. If exit code 2 (timeout): Report timeout
      4. If exit code 1 (error): Report error details
      Report the outcome (success with file path, or failure with reason).
      ```

      **Output filename logic:**
      - Single episode: `podcast-YYYY-MM-DD.mp3`
      - Grouped episodes: `podcast-<theme-slug>-YYYY-MM-DD.mp3`
      - Topic-filtered: `podcast-<topic>-YYYY-MM-DD.mp3`
      - Saved to `config.output_path`

      **Parallel execution:** When multiple episode groups exist, launch all background agents in parallel (one per episode). Each episode gets its own notebook, run record, and artifact.
  ```

- New string:
  ```
  6k. **Spawn background agent (REVISED — assemble, then transcribe with actual offset):**

      **Output filename stem:**
      - Single episode: `podcast-YYYY-MM-DD`
      - Grouped episodes: `podcast-<theme-slug>-YYYY-MM-DD`
      - Topic-filtered: `podcast-<topic>-YYYY-MM-DD`
      Let `<stem>` = the chosen filename stem; paths become `<output_path>/<stem>.raw.mp3`, `<output_path>/<stem>.mp3`, `<output_path>/<stem>.vtt`, `<output_path>/<stem>.transcript.md`.

      Use Agent tool with `run_in_background: true`:
      ```
      Wait for NotebookLM artifact, then assemble intro music, then transcribe.

      1. source <venv>/bin/activate && notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
         If exit != 0: report and stop.

      2. source <venv>/bin/activate && notebooklm download audio <output_path>/<stem>.raw.mp3 -n <notebook_id>
         If exit != 0: report and stop.

      3. intro_applied = false
         actual_vtt_offset = 0.0
         If <intro_music_configured>:
           Run: python3 <skill_dir>/scripts/assemble_audio.py \
             --raw-audio <output_path>/<stem>.raw.mp3 \
             --intro <intro_music> \
             --output <output_path>/<stem>.mp3 \
             --intro-length <effective_intro_length> \
             --crossfade <effective_crossfade> \
             --json
           Parse the JSON from stdout.
           If success AND intro_applied=true:
             intro_applied = true
             actual_vtt_offset = <final_offset_seconds from the JSON>
           Else:
             cp <output_path>/<stem>.raw.mp3 <output_path>/<stem>.mp3
             intro_applied = false
             actual_vtt_offset = 0.0
         Else:
           cp <output_path>/<stem>.raw.mp3 <output_path>/<stem>.mp3

      4. transcript_applied = false
         speaker_count = 0
         If <transcript_enabled>:
           Run: python3 <skill_dir>/scripts/transcribe_audio.py \
             --audio <output_path>/<stem>.raw.mp3 \
             --hosts '<json-encoded host_pool>' \
             --output-vtt <output_path>/<stem>.vtt \
             --output-md <output_path>/<stem>.transcript.md \
             --vtt-offset-seconds <actual_vtt_offset> \
             --model <transcript.model> \
             --device <transcript.device> \
             --language <transcript.language> \
             --title "全栈AI — <theme> (YYYY-MM-DD)" \
             --json
           Parse the JSON.
           If success: transcript_applied=true; speaker_count from the JSON.
           Else: transcript_applied=false (do NOT fail the episode).

      5. Report a JSON summary to stdout:
          {
            "raw_audio": "<output_path>/<stem>.raw.mp3",
            "final_audio": "<output_path>/<stem>.mp3",
            "intro_applied": <bool>,
            "vtt_offset_used": <seconds>,
            "transcript": {
               "vtt": "<output_path>/<stem>.vtt" | null,
               "markdown": "<output_path>/<stem>.transcript.md" | null,
               "applied": <bool>,
               "speaker_count": <int>
            },
            "warnings": [<per-stage warnings>]
          }

      Shell-quote every path. If a path contains spaces or Chinese characters
      or other shell-special chars, pass values through argv arrays to
      subprocess.run — never inline user-controlled strings into a shell string.
      ```

      **Parallel execution:** When multiple episode groups exist, launch all background agents in parallel (one per episode). Each episode gets its own notebook, run record, and artifact.

      **Recovery path (when skip_generation=true from step 6c):** Skip steps 1 and 2;
      assume the raw audio already exists at `<output_path>/<stem>.raw.mp3`. Execute
      only steps 3 and 4 (assembly + transcription).
  ```

- [ ] **Step 5: Update step 7 (on-success finalization) to write `postproc_hash` + `podcast_outputs` + new sidecar fields**

Find the existing step 7 (around line 524). Apply this edit:

- Old string (the bullet about writing the sidecar manifest):
  ```
      - **Write sidecar manifest:** Write `<audio_path>.manifest.yaml` alongside the generated
        MP3 file. Include: `audio` (filename), `topic` (short English topic label derived from
        the lesson group name), `notebook_id`, `generated_date`, `depth` estimated from source
        lesson complexity, `concepts_covered` extracted from source lesson headings and content,
        `open_threads` from related topics mentioned but not deeply covered, and `source_lessons`
        as the basenames of the lesson files used. **Do NOT write to `episodes.yaml`** — that is
        `kb-publish`'s responsibility (single-writer rule).
  ```

- New string:
  ```
      - **Update run record:** Populate `state.runs[...]` with:
        - `params_hash`, `postproc_hash` (from step 6b')
        - `podcast_outputs` object:
          ```yaml
          podcast_outputs:
            raw_audio: <output_path>/<stem>.raw.mp3
            final_audio: <output_path>/<stem>.mp3
            vtt: <output_path>/<stem>.vtt             # null if transcript disabled/failed
            transcript_md: <output_path>/<stem>.transcript.md    # null if transcript disabled/failed
            manifest: <output_path>/<stem>.mp3.manifest.yaml
            intro_applied: <bool from background-agent JSON>
            transcript_applied: <bool from background-agent JSON>
          ```
        - Keep `artifacts[0].output_files = [final_audio]` for backward compatibility.
      - **Write sidecar manifest:** Write `<output_path>/<stem>.mp3.manifest.yaml` alongside the generated
        MP3 file. Include the existing fields (`audio`, `topic`, `notebook_id`, `generated_date`, `depth`,
        `concepts_covered`, `open_threads`, `source_lessons`) AND the new fields:
        ```yaml
        intro_applied: <bool>
        hosts: [<host_pool[0]>, <host_pool[1]>]
        transcript:
          vtt: <basename of vtt or null>
          markdown: <basename of transcript_md or null>
          applied: <bool>
          speaker_count: <int>
        ```
        **Do NOT write to `episodes.yaml`** — that is `kb-publish`'s responsibility (single-writer rule).
  ```

- [ ] **Step 6: Update the Cleanup Workflow to delete `raw_audio` when pruning records**

Find the `### Cleanup Workflow` section (around line 770). Apply this edit:

- Old string:
  ```
  ### Cleanup Workflow

  **Command:** `cleanup [--days N]`

  1. Read `notebooks` from state file

  2. For each notebook where `created` is older than N days (default `config.cleanup_days`, which defaults to 7):
     - Confirm with user before first deletion, then batch the rest
     - `notebooklm delete <notebook_id>`
     - Remove from `notebooks` in state

  3. Also clean up `pending` or `failed` notebooks older than 1 day (likely orphaned)

  4. Prune `runs` older than `cleanup_days * 2`

  5. Write state (atomic)
  ```

- New string:
  ```
  ### Cleanup Workflow

  **Command:** `cleanup [--days N] [--raw-audio]`

  1. Read `notebooks` from state file

  2. For each notebook where `created` is older than N days (default `config.cleanup_days`, which defaults to 7):
     - Confirm with user before first deletion, then batch the rest
     - `notebooklm delete <notebook_id>`
     - Remove from `notebooks` in state

  3. Also clean up `pending` or `failed` notebooks older than 1 day (likely orphaned)

  4. Prune `runs` older than `cleanup_days * 2`. For each pruned podcast run whose
     record contains `podcast_outputs.raw_audio`:
     - If the file exists on disk, delete it. Log the deletion.
     - Preserve `final_audio`, `vtt`, `transcript_md`, and `manifest` — those are
       the user's deliverables and may still be referenced by `kb-publish` state.

  5. If `--raw-audio` is passed: also scan all current (non-pruned) podcast runs and
     delete every `podcast_outputs.raw_audio` file that exists, after user confirmation.
     Update each affected run record to set `raw_audio` to null (so future dedup knows
     the raw is no longer available — fall back to regeneration if post-processing
     settings change).

  6. Write state (atomic).
  ```

- [ ] **Step 7: Sanity-check internal consistency**

Run:

```bash
grep -n "podcast_outputs\|postproc_hash\|postproc_complete\|rendered_prompt\|host_pool\|全栈AI\|assemble_audio\|transcribe_audio" plugins/kb/skills/kb-notebooklm/SKILL.md
```

Expected: multiple hits in the podcast workflow, preamble, cleanup, and step 7 sections. No references to `My Lessons Learned` should appear in any host-facing or audience-facing text (internal MLL labels are fine in notebook titles etc.).

Run one more consistency check — search for "rename raw" / "transcribe-then-assemble":

```bash
grep -n "rename raw\|transcribe-then-assemble\|transcribe before assemble" plugins/kb/skills/kb-notebooklm/SKILL.md
```

Expected: no hits. (If hits appear, the edits above missed something; reopen the file and reconcile to the spec.)

- [ ] **Step 8: Commit**

```bash
git add plugins/kb/skills/kb-notebooklm/SKILL.md
git commit -m "feat(kb-notebooklm): wire assemble + transcribe into podcast workflow

- Adds steps 6a' (render prompt before hashing), 6a'' (resolve post-processing
  config, incl. intro ffprobe/hashing), 6b' (compute params_hash + postproc_hash
  via postproc_hashing.py).
- Rewrites step 6c dedup to check postproc_hash + postproc_complete predicate
  and re-run post-processing only from retained raw audio when possible.
- Step 6i now uses the pre-rendered prompt from 6a' (no inline rendering).
- Step 6k background agent now assembles (cp fallback) then transcribes with
  actual_vtt_offset from assembly JSON.
- Step 7 writes podcast_outputs structured record + new sidecar fields
  (intro_applied, hosts, transcript.*).
- Cleanup workflow deletes raw_audio on record prune; adds --raw-audio
  subflag for on-demand pruning."
```

---

## Task 7: Update `kb-publish/SKILL.md` — preserve new sidecar fields through state transitions

**Goal:** Extend `kb-publish`'s sidecar import (Step 2b) and registry update (Step 8b) to copy the new `intro_applied`, `hosts`, and `transcript` fields through to `episodes.yaml`, treating them as opaque pass-through data.

**Files:**
- Modify: `plugins/kb/skills/kb-publish/SKILL.md`

- [ ] **Step 1: Extend Step 2b — sidecar import**

Open `plugins/kb/skills/kb-publish/SKILL.md` and find Step 2b (around line 121). Apply this edit:

- Old string:
  ```
  6. If no existing entry: create a schema-complete entry with `status: generated`, `id: null`, `title: null`, `description: null`, `date: null`, and all content manifest fields from the sidecar (`topic`, `depth`, `concepts_covered`, `open_threads`, `source_lessons`, `notebook_id`).
  7. Write the registry atomically (write to temp file, rename).
  8. Delete the sidecar file only after successful registry write.
  ```

- New string:
  ```
  6. If no existing entry: create a schema-complete entry with `status: generated`, `id: null`, `title: null`, `description: null`, `date: null`, all content manifest fields from the sidecar (`topic`, `depth`, `concepts_covered`, `open_threads`, `source_lessons`, `notebook_id`), AND the new post-processing fields from the sidecar (pass through opaquely): `intro_applied`, `hosts`, and the nested `transcript` object (`vtt`, `markdown`, `applied`, `speaker_count`). Treat these as opaque — `kb-publish` does not interpret their values.
  7. Write the registry atomically (write to temp file, rename).
  8. Delete the sidecar file only after successful registry write.
  ```

Also, update the merge branch (step 5 of 2b):

- Old string:
  ```
  5. If existing entry has `status: generated` or `draft`: merge any fields from the sidecar that are currently null/empty.
  ```
- New string:
  ```
  5. If existing entry has `status: generated` or `draft`: merge any fields from the sidecar that are currently null/empty. This includes the new post-processing fields (`intro_applied`, `hosts`, `transcript.*`) — preserve them on the registry entry even though `kb-publish` does not interpret their values.
  ```

- [ ] **Step 2: Extend Step 8b — registry update after upload**

Find Step 8b (around line 332). Apply this edit:

- Old string:
  ```
  4. **If entry exists with `status: generated` or `draft`** (state transition):
     - Update `status` to `published` (or `draft` if `--mode draft`).
     - If publishing and `id` is `null`: assign `id` from `next_id`, set `date` to today, increment `next_id`.
     - Merge `title`, `description`, and `topic` from the current upload.
     - Content manifest fields (`concepts_covered`, `open_threads`, `source_lessons`, `depth`) are already populated from the sidecar — preserve them.
  ```

- New string:
  ```
  4. **If entry exists with `status: generated` or `draft`** (state transition):
     - Update `status` to `published` (or `draft` if `--mode draft`).
     - If publishing and `id` is `null`: assign `id` from `next_id`, set `date` to today, increment `next_id`.
     - Merge `title`, `description`, and `topic` from the current upload.
     - Content manifest fields (`concepts_covered`, `open_threads`, `source_lessons`, `depth`) are already populated from the sidecar — preserve them.
     - **Post-processing fields** (`intro_applied`, `hosts`, `transcript`) are already populated from the sidecar — preserve them. Do not overwrite or null them out.
  ```

- [ ] **Step 3: Extend Step 8b — the "create new entry" branch**

Apply this edit to the step-5 "If no entry exists" list:

- Old string:
  ```
  5. **If no entry exists** (new audio without prior generation):
     - Create a schema-complete entry with all fields:
       - `audio`: `basename(audio_path)`
       - `topic`: from `topic_summary` in Step 3
       - `id`: if publishing, assign from `next_id` and increment. If draft, set `null`.
       - `title`: the generated title (with or without EP prefix per mode)
       - `description`: the generated description
       - `date`: today if publishing, `null` if draft
       - `status`: `published` or `draft` per mode
       - `notebook_id`: `null` (non-NotebookLM audio)
       - `depth`: estimated from topic analysis in Step 3
       - `concepts_covered`: from key concepts in Step 3
       - `open_threads`: `[]` (unknown for non-NotebookLM audio)
       - `source_lessons`: `[]`
  ```

- New string:
  ```
  5. **If no entry exists** (new audio without prior generation):
     - Create a schema-complete entry with all fields:
       - `audio`: `basename(audio_path)`
       - `topic`: from `topic_summary` in Step 3
       - `id`: if publishing, assign from `next_id` and increment. If draft, set `null`.
       - `title`: the generated title (with or without EP prefix per mode)
       - `description`: the generated description
       - `date`: today if publishing, `null` if draft
       - `status`: `published` or `draft` per mode
       - `notebook_id`: `null` (non-NotebookLM audio)
       - `depth`: estimated from topic analysis in Step 3
       - `concepts_covered`: from key concepts in Step 3
       - `open_threads`: `[]` (unknown for non-NotebookLM audio)
       - `source_lessons`: `[]`
       - `intro_applied`: `null` (unknown for non-NotebookLM audio)
       - `hosts`: `null` (unknown)
       - `transcript`: `null` (unknown)
  ```

- [ ] **Step 4: Extend the Episode Registry schema documentation**

Find the `### Episode Registry` section (around line 18). Apply this edit:

- Old string:
  ```
  ```yaml
  episodes:
    - id: 1                   # assigned at publish time (null until published)
      title: "EP1 | 为什么你的顶级显卡在大模型面前会'罢工'？"
      topic: "GPU Computing & CUDA"  # short English topic label
      description: "从GPU架构讲起..."  # 节目简介 (set at publish time)
      date: 2026-04-13         # publish date
      status: published        # generated → draft → published
      audio: podcast-hardware-2026-04-12.mp3   # stable key
      notebook_id: "uuid"      # links to .notebooklm-state.yaml
      depth: intro             # intro | intermediate | deep-dive
      concepts_covered:
        - name: "GPU vs CPU Architecture"
          depth: explained     # mentioned | explained | deep-dive
        - name: "CUDA Programming Model"
          depth: explained
      open_threads:
        - "Tensor Cores and mixed-precision training"
      source_lessons: []
  next_id: 2                   # next publication ID
  ```
  ```

- New string:
  ```
  ```yaml
  episodes:
    - id: 1                   # assigned at publish time (null until published)
      title: "EP1 | 为什么你的顶级显卡在大模型面前会'罢工'？"
      topic: "GPU Computing & CUDA"  # short English topic label
      description: "从GPU架构讲起..."  # 节目简介 (set at publish time)
      date: 2026-04-13         # publish date
      status: published        # generated → draft → published
      audio: podcast-hardware-2026-04-12.mp3   # stable key
      notebook_id: "uuid"      # links to .notebooklm-state.yaml
      depth: intro             # intro | intermediate | deep-dive
      concepts_covered:
        - name: "GPU vs CPU Architecture"
          depth: explained     # mentioned | explained | deep-dive
        - name: "CUDA Programming Model"
          depth: explained
      open_threads:
        - "Tensor Cores and mixed-precision training"
      source_lessons: []
      # Post-processing metadata (opaque to kb-publish; populated by kb-notebooklm sidecar):
      intro_applied: true      # or false; null for non-NotebookLM audio
      hosts: ["瓜瓜龙", "海发菜"]
      transcript:
        vtt: podcast-hardware-2026-04-12.vtt
        markdown: podcast-hardware-2026-04-12.transcript.md
        applied: true
        speaker_count: 2
  next_id: 2                   # next publication ID
  ```
  ```

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/SKILL.md
git commit -m "feat(kb-publish): preserve podcast post-processing fields through state transitions

kb-notebooklm's sidecar manifest now includes intro_applied, hosts, and
transcript.* fields. kb-publish passes them through opaquely in both
the import path (Step 2b) and the registry update path (Step 8b), and
documents them in the episodes.yaml schema. kb-publish does not
interpret their values — they're kept so future tooling (e.g.,
uploading VTTs to 小宇宙, if their API ever supports it) can use them."
```

---

## Task 8: Update `kb-init/SKILL.md` — one-time setup for the new capabilities

**Goal:** Extend kb-init to install the new venv dependencies, verify ffmpeg/ffprobe, walk the user through the HuggingFace token + dual pyannote license acceptance, and persist `transcript.enabled` based on setup outcome.

**Files:**
- Modify: `plugins/kb/skills/kb-init/SKILL.md`

- [ ] **Step 1: Read the current kb-init SKILL to find the notebooklm setup section**

Run:

```bash
grep -n "notebooklm\|venv\|HF\|huggingface\|pyannote\|whisper\|faster-whisper" plugins/kb/skills/kb-init/SKILL.md | head -30
```

Locate where the notebooklm venv is set up (the skill has a multi-integration setup flow — find the notebooklm block).

- [ ] **Step 2: Extend the notebooklm venv setup with new deps + ffmpeg check + HF token prompts**

Find the notebooklm-related section. Append a new subsection (or extend the existing one — use your judgment based on the file's structure) describing podcast post-processing setup. Insert this block somewhere logical inside the notebooklm setup section:

```markdown
### Podcast Post-Processing Setup (new — run as part of notebooklm bootstrap)

If `integrations.notebooklm.enabled: true`, also set up the prerequisites for intro music assembly and transcript generation.

**A. Install additional venv dependencies** (both for fresh setup and for existing venvs that predate this feature):

```bash
source <venv_path>/bin/activate && \
  pip install -q 'faster-whisper>=1.0.0' 'pyannote.audio>=3.1.0' 'PyYAML>=6.0'
```

Verify the imports land:

```bash
source <venv_path>/bin/activate && \
  python3 -c "import faster_whisper, pyannote.audio, yaml; print('OK')"
```

If the verify step fails, report the stderr to the user, point at `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt`, and STOP.

**B. Verify ffmpeg + ffprobe are on PATH:**

```bash
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && echo "ffmpeg OK" || echo "ffmpeg MISSING"
```

If missing, guide the user:

> 封面与 intro music 功能需要 ffmpeg。请运行:
> ```
> brew install ffmpeg
> ```
> 完成后重新运行 `/kb-init`。

Record `ffmpeg_available = <bool>`. If unavailable, the skill will proceed but write `intro_music: null` into `kb.yaml` so assembly silently skips per-episode.

**C. HuggingFace token + pyannote license acceptance (for transcripts):**

Check if `HUGGINGFACE_TOKEN` is already set:

```bash
test -n "$HUGGINGFACE_TOKEN" && echo "Token present" || echo "Token missing"
```

If missing, ask the user:

> 是否要启用podcast 字幕/转录功能（需要 HuggingFace 帐号 + 接受两个 pyannote 模型协议）？
> - 启用后可生成 WebVTT 字幕 + markdown 逐字稿
> - 不启用也能用 podcast 功能，仅跳过转录

- **启用 (yes):**
  1. 在浏览器打开 https://huggingface.co/pyannote/segmentation-3.0 并点击 "Agree and access repository"
  2. 在浏览器打开 https://huggingface.co/pyannote/speaker-diarization-3.1 并点击 "Agree and access repository"
  3. 在 https://huggingface.co/settings/tokens 创建一个 read-scope token
  4. 将以下内容加入你的 shell profile (~/.zshrc 或 ~/.bashrc):
     ```
     export HUGGINGFACE_TOKEN=hf_...
     ```
  5. 运行 `source ~/.zshrc` 或重启终端
  6. 完成后按 Enter 继续

  Verify:
  ```bash
  test -n "$HUGGINGFACE_TOKEN" && echo "Token set" || echo "Token still missing"
  ```
  If still missing, warn the user and fall back to `transcript_enabled = false`.

- **跳过 (no):** Set `transcript_enabled = false`.

If the token IS set, attempt a dry-run model download to verify license acceptance:

```bash
source <venv_path>/bin/activate && \
  python3 -c "
from pyannote.audio import Pipeline
import os
try:
    Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token=os.environ['HUGGINGFACE_TOKEN'])
    print('License check: OK')
except Exception as e:
    print(f'License check FAILED: {e}')
    raise SystemExit(1)
"
```

If this fails, warn the user that one or both licenses haven't been accepted. Point them back to the two URLs and fall back to `transcript_enabled = false`.

**D. Persist the outcome to `kb.yaml`:**

Non-destructive merge into `kb.yaml`. Under `integrations.notebooklm.podcast` (create if missing):

```yaml
integrations:
  notebooklm:
    podcast:
      transcript:
        enabled: <transcript_enabled>       # explicit: true or false based on token/license outcome
        model: "large-v3"
        device: "auto"
        language: "zh"
      hosts: ["瓜瓜龙", "海发菜"]
      extra_host_names: []
      intro_music_length_seconds: 12
      intro_crossfade_seconds: 3
      # intro_music: <omit this line if ffmpeg is unavailable; else leave commented
      #              as a hint for the user to set a path later>
```

**E. Note on model caching:** `faster-whisper` uses the standard HuggingFace cache at `~/.cache/huggingface/hub/`. If the user has VoxToriApp installed on the same machine, the `large-v3` model is likely already cached at `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3` and will be reused automatically. Do NOT override `HF_HOME` in this skill.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb-init/SKILL.md
git commit -m "feat(kb-init): add podcast post-processing setup

Extends the notebooklm bootstrap to install faster-whisper and
pyannote.audio into the existing venv, verifies ffmpeg/ffprobe are
available, walks the user through HuggingFace token + dual pyannote
license acceptance (segmentation-3.0 + speaker-diarization-3.1), runs
a dry-run model download to verify licenses, and persists
transcript.enabled in kb.yaml based on setup outcome. Shares the
faster-whisper large-v3 cache with VoxToriApp."
```

---

## Task 9: Version bump and final commit

**Goal:** Bump the plugin version so installed plugins pick up the new capabilities after the user runs `claude plugin marketplace update llm-kb-skills && claude plugin install kb@llm-kb-skills`.

**Files:**
- Modify: `plugins/kb/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump the version from 1.13.2 to 1.14.0**

This is a minor bump (new feature set, no breaking changes). Apply this edit:

- Old string: `"version": "1.13.2",`
- New string: `"version": "1.14.0",`

- [ ] **Step 2: Verify the manifest is valid JSON**

```bash
python3 -c "import json; json.load(open('plugins/kb/.claude-plugin/plugin.json')); print('valid')"
```

Expected: `valid`.

- [ ] **Step 3: Run the full unit test suite one more time**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills && \
  source ~/notebooklm-py/.venv/bin/activate && \
  pytest plugins/kb/skills/kb-notebooklm/scripts/tests/ -v
```

Expected: all tests green. If anything fails, reopen the failing test/file and reconcile before committing.

- [ ] **Step 4: Commit**

```bash
git add plugins/kb/.claude-plugin/plugin.json
git commit -m "chore: bump kb plugin to 1.14.0 for podcast enhancements

Ships intro music crossfade, named hosts (瓜瓜龙 / 海发菜),
speaker-labeled transcripts (WebVTT + markdown), and the 全栈AI
brand fix. Minor bump — additive config keys only, no breaking
changes to state schema or CLI contract."
```

- [ ] **Step 5: Print a summary for the user**

Report:

```
Implementation complete on branch feature/podcast-intro-hosts-transcript.

What was built:
- 2 new Python scripts (assemble_audio.py, transcribe_audio.py) with 35+ unit tests
- 1 shared helper (postproc_hashing.py) with 17 unit tests
- Prompt updated (brand fix to 全栈AI + {hosts} placeholder + HOST INTRODUCTION)
- SKILL.md updated (prompt-before-hash reorder, postproc_hash, podcast_outputs, background agent v2, cleanup)
- kb-publish updated to preserve new sidecar fields
- kb-init updated to bootstrap the new deps + HF tokens

Next steps:
- Review the procedural end-to-end test checklist in the spec (section "Testing & Verification")
- Run `/kb-init` against your KB project to install the new venv deps + HF setup
- Run `/kb-notebooklm podcast` against a real lessons directory to verify the full flow end-to-end
- When ready, merge feature/podcast-intro-hosts-transcript into master and tag v1.14.0
```

---

## Self-Review

I walked the plan top-to-bottom against the spec's sections 1–9 and the "Testing & Verification" section. Coverage check:

- Section 1 (prompt changes, brand fix) → Task 5.
- Section 2 (host pool resolution in SKILL.md) → Task 6 step 2.
- Section 3 (assemble_audio.py) → Task 3 + tests.
- Section 4 (transcribe_audio.py) → Task 4 + tests (4.1 whisper, 4.2 pyannote, 4.3 alignment+labeling, 4.4 outputs).
- Section 5 (step 6k background agent) → Task 6 step 4.
- Section 6 (dedup, ordering, cleanup) → Task 2 (hashing + predicate unit tests), Task 6 steps 2, 5, 6.
- Section 7 (sidecar fields + kb-publish preservation) → Task 6 step 5 (writes the fields) + Task 7 (preserves them).
- Section 8 (kb-init setup) → Task 8.
- Section 9 (workflow summary table) → internalized across Task 6 subtasks.

Unit test items from the spec:
- assemble_audio tests (6 items) → Task 3 step 1 (test file covers them: 5 preflight tests, 2 ffmpeg argv tests, 2 JSON shape tests, 2 ffprobe-integration tests, 11 total — exceeds spec).
- transcribe_audio tests (10 items) → Task 4 step 1 (test file covers them across 24 tests, including timestamp formatting, VTT escaping, voice tag escaping, markdown merging, diarization label mapping, segment splitting, VTT offset sanity, self-intro swap, title derivation, JSON shapes).
- params_hash tests (3 items) → Task 2 step 1 (extended to 17 tests).

Procedural end-to-end tests (11 items in spec) are deferred to the human post-implementation — not automatable.

**Placeholder scan:** No "TODO", "TBD", "fill in details" in any task. Every step has complete code or exact commands. Exception: the commit step in Task 1 intentionally reflects "no runtime behavior yet" — that's descriptive, not a placeholder.

**Type consistency check:** `postproc_hash` / `params_hash` signatures match between the hash-calling pseudocode in Task 6 Step 2 and the Python function definitions in Task 2 Step 3. `split_segment_by_diarization` / `map_speakers_to_hosts` / `render_vtt` / `render_markdown` / `derive_title` / `build_result_json` names are consistent between the test file in Task 4 Step 1 and the implementation in Task 4 Step 3. `PreflightResult` / `probe_duration` / `build_ffmpeg_argv` / `ProbeError` are consistent between Task 3 Step 1 and Task 3 Step 3. `postproc_complete` signature (`outputs, *, intro_music_configured, transcript_enabled`) is consistent between Task 2 Step 1 (tests), Task 2 Step 3 (implementation), and Task 6 Step 2 (shell-out invocation).

**One known Python-packaging wrinkle, documented in place:** The skill directory is `kb-notebooklm` (with a hyphen), which Python can't import as a dotted package. All test files use `sys.path.insert` with the scripts directory, bypassing dotted imports entirely. This is flagged in Task 2 Step 2 and applied uniformly across Tasks 2, 3, 4.

No changes needed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-podcast-intro-hosts-transcript-implementation.md`. Per your user-level convention, I'm auto-continuing with **Subagent-Driven** execution (your CLAUDE.md says: always choose subagent-driven when the superpowers plugin presents execution options, no need to ask).
