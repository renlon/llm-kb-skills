"""Smoke tests for backfill_index.py — file-resolution helpers and CLI show/lock tests.

The end-to-end flow is integration-tested via the live backfill of EP1+EP2
(Task 11 of the implementation plan).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import backfill_index as B
from lock import LockBusyError, LOCK_FILENAME


# ---------------------------------------------------------------------------
# Helpers for building minimal kb.yaml + episodes.yaml fixtures
# ---------------------------------------------------------------------------

def _show_dict(show_id: str = "quanzhan-ai", registry: str = "episodes.yaml") -> dict:
    return {
        "id": show_id,
        "title": "全栈AI",
        "description": "Test show",
        "language": "zh_Hans",
        "hosts": ["瓜瓜龙", "海发菜"],
        "extra_host_names": [],
        "intro_music": None,
        "intro_music_length_seconds": 12,
        "intro_crossfade_seconds": 3,
        "podcast_format": "deep-dive",
        "podcast_length": "long",
        "transcript": {"enabled": True, "model": "large-v3", "device": "auto", "language": "zh"},
        "episodes_registry": registry,
        "wiki_episodes_dir": f"episodes/{show_id}",
        "xiaoyuzhou": {"podcast_id": f"pod-{show_id}"},
    }


def _make_kb_yaml(tmp_path: Path, *, shows: list[dict] | None = None) -> Path:
    """Write a minimal kb.yaml for backfill tests and return its path.

    The kb.yaml shape matches what load_shows() expects:
      integrations.notebooklm.{enabled, wiki_path, output_path, venv_path}
      integrations.shows[...]
    """
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir(exist_ok=True)

    if shows is None:
        shows = [_show_dict()]

    data = {
        "integrations": {
            "notebooklm": {
                "enabled": True,
                "wiki_path": str(wiki_dir),
                "output_path": str(output_dir),
                "venv_path": str(venv_dir),
            },
            "shows": shows,
        }
    }
    kb_path = tmp_path / "kb.yaml"
    kb_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return kb_path


def _make_episodes_yaml(tmp_path: Path, episodes: list[dict] | None = None, filename: str = "episodes.yaml") -> Path:
    data = {"episodes": episodes or [], "next_id": 1}
    path = tmp_path / filename
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_resolve_audio_direct_hit(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "podcast-a.mp3").write_bytes(b"x")
    assert B._resolve_audio_path(out, "podcast-a.mp3") == out / "podcast-a.mp3"


def test_resolve_audio_notebooklm_subdir(tmp_path):
    out = tmp_path / "out"
    (out / "notebooklm").mkdir(parents=True)
    (out / "notebooklm" / "podcast-b.mp3").write_bytes(b"x")
    assert B._resolve_audio_path(out, "podcast-b.mp3") == out / "notebooklm" / "podcast-b.mp3"


def test_resolve_audio_missing_returns_none(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert B._resolve_audio_path(out, "nope.mp3") is None


def test_transcript_exists_uses_registry_path_when_present(tmp_path):
    audio_dir = tmp_path / "a"
    audio_dir.mkdir()
    (audio_dir / "podcast-x.mp3").write_bytes(b"x")
    (audio_dir / "podcast-x.transcript.md").write_text("hello", encoding="utf-8")
    (audio_dir / "podcast-x.vtt").write_text("WEBVTT\n", encoding="utf-8")
    entry = {
        "audio": "podcast-x.mp3",
        "transcript": {"markdown": "podcast-x.transcript.md", "vtt": "podcast-x.vtt", "applied": True},
    }
    md, vtt = B._transcript_exists(entry, audio_dir)
    assert md == audio_dir / "podcast-x.transcript.md"
    assert vtt == audio_dir / "podcast-x.vtt"


def test_transcript_exists_falls_back_to_sibling(tmp_path):
    audio_dir = tmp_path / "a"
    audio_dir.mkdir()
    (audio_dir / "podcast-x.mp3").write_bytes(b"x")
    (audio_dir / "podcast-x.transcript.md").write_text("hello", encoding="utf-8")
    entry = {"audio": "podcast-x.mp3"}  # no transcript block at all
    md, vtt = B._transcript_exists(entry, audio_dir)
    assert md == audio_dir / "podcast-x.transcript.md"
    assert vtt is None  # vtt not generated


def test_transcript_exists_returns_none_when_nothing(tmp_path):
    audio_dir = tmp_path / "a"
    audio_dir.mkdir()
    (audio_dir / "podcast-x.mp3").write_bytes(b"x")
    entry = {"audio": "podcast-x.mp3"}
    md, vtt = B._transcript_exists(entry, audio_dir)
    assert md is None and vtt is None


def test_update_registry_replaces_concepts_and_transcript(tmp_path):
    reg = {
        "episodes": [
            {"id": 1, "title": "EP1", "audio": "a.mp3", "status": "published",
             "concepts_covered": [{"name": "old", "depth": "mentioned"}],
             "open_threads": ["old thread"],
             "transcript": {"applied": False, "markdown": None, "vtt": None}},
        ],
    }
    extraction = {
        "concepts": [
            {"slug": "wiki/foo/bar", "depth_this_episode": "explained",
             "what": "w", "why_it_matters": "y", "key_points": []}
        ],
        "open_threads": [{"slug": None, "note": "new thread", "existed_before": False}],
    }
    audio_dir = tmp_path
    md_path = audio_dir / "a.transcript.md"
    vtt_path = audio_dir / "a.vtt"
    md_path.write_text("x", encoding="utf-8")
    vtt_path.write_text("x", encoding="utf-8")

    B._update_registry_for_episode(reg, 1, extraction, vtt_path, md_path)
    ep = reg["episodes"][0]
    assert ep["concepts_covered"] == [{"name": "bar", "depth": "explained"}]
    assert ep["open_threads"] == ["new thread"]
    assert ep["transcript"]["markdown"] == "a.transcript.md"
    assert ep["transcript"]["vtt"] == "a.vtt"
    assert ep["transcript"]["applied"] is True


# ---------------------------------------------------------------------------
# Multi-show CLI flag tests (Task 10)
# ---------------------------------------------------------------------------

def _make_fake_scripts_dir(tmp_path: Path) -> Path:
    """Create a fake _SCRIPTS_DIR tree under tmp_path so that:

    - _SCRIPTS_DIR.parent.parent.parent / "skills" / "kb-notebooklm" / "scripts" / "transcribe_audio.py"
      exists (satisfies the skill-dir check in main())
    - _SCRIPTS_DIR.parent / "prompts" / "episode-wiki-extract.md" exists (satisfies the prompt check)

    The layout mirrors the real tree:
      tmp_path/
        kb/                           ← plugin root (_SCRIPTS_DIR.parent.parent.parent)
          skills/
            kb-notebooklm/
              scripts/
                transcribe_audio.py
            kb-publish/
              prompts/
                episode-wiki-extract.md
              scripts/                ← _SCRIPTS_DIR returned here
    """
    scripts_dir = tmp_path / "kb" / "skills" / "kb-publish" / "scripts"
    scripts_dir.mkdir(parents=True)

    # transcribe_audio.py stub
    transcribe_dir = tmp_path / "kb" / "skills" / "kb-notebooklm" / "scripts"
    transcribe_dir.mkdir(parents=True)
    (transcribe_dir / "transcribe_audio.py").write_text("", encoding="utf-8")

    # prompt template stub
    prompts_dir = tmp_path / "kb" / "skills" / "kb-publish" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "episode-wiki-extract.md").write_text(
        "stub {transcript} {episode_metadata} {concept_catalog} {recent_episodes}",
        encoding="utf-8",
    )

    return scripts_dir


def test_backfill_rejects_ambiguous_show_without_flag(tmp_path):
    """Two shows + no --show → exit code 2 (AmbiguousShowError)."""
    kb_path = _make_kb_yaml(
        tmp_path,
        shows=[
            _show_dict("show-a", registry="episodes-a.yaml"),
            _show_dict("show-b", registry="episodes-b.yaml"),
        ],
    )
    rc = B.main(["--kb-yaml", str(kb_path), "--all"])
    assert rc == 2


def test_backfill_unknown_show_id(tmp_path):
    """Single show 'show-a', --show other → exit code 2 (ShowNotFoundError)."""
    kb_path = _make_kb_yaml(
        tmp_path,
        shows=[_show_dict("show-a", registry="episodes.yaml")],
    )
    rc = B.main(["--kb-yaml", str(kb_path), "--show", "other", "--all"])
    assert rc == 2


def test_backfill_explicit_show_selects(tmp_path, monkeypatch):
    """Two shows + --show show-b → proceeds with show-b registry (not show-a's)."""
    _make_episodes_yaml(tmp_path, episodes=[], filename="episodes-a.yaml")
    _make_episodes_yaml(tmp_path, episodes=[], filename="episodes-b.yaml")

    kb_path = _make_kb_yaml(
        tmp_path,
        shows=[
            _show_dict("show-a", registry="episodes-a.yaml"),
            _show_dict("show-b", registry="episodes-b.yaml"),
        ],
    )

    fake_scripts_dir = _make_fake_scripts_dir(tmp_path)
    monkeypatch.setattr(B, "_SCRIPTS_DIR", fake_scripts_dir)

    # With no published episodes, main should complete with rc=0
    # and select show-b (registry episodes-b.yaml exists with zero episodes).
    rc = B.main(["--kb-yaml", str(kb_path), "--show", "show-b", "--all"])
    # show-b registry exists but has 0 published episodes → "No published episodes to backfill."
    # rc=0 is expected (no episodes; the lock path won't be reached either)
    assert rc == 0


def test_backfill_acquires_mutation_lock(tmp_path, monkeypatch):
    """backfill main() acquires kb_mutation_lock with command='backfill-index'."""
    # Must have at least one published episode so the lock path is reached.
    published_ep = {"id": 1, "status": "published", "audio": "ep1.mp3", "topic": "test", "date": "2026-01-01"}
    _make_episodes_yaml(tmp_path, episodes=[published_ep], filename="episodes.yaml")
    kb_path = _make_kb_yaml(tmp_path, shows=[_show_dict()])

    acquired_with = {}

    from contextlib import contextmanager

    @contextmanager
    def fake_lock(project_root, command, *, timeout=5.0):
        acquired_with["project_root"] = project_root
        acquired_with["command"] = command
        yield

    monkeypatch.setattr(B, "kb_mutation_lock", fake_lock)

    # Stub backfill_episode so we don't need real audio/transcript/Haiku
    def fake_backfill_episode(**kwargs):
        raise RuntimeError("stub — episode intentionally failed")

    monkeypatch.setattr(B, "backfill_episode", fake_backfill_episode)

    fake_scripts_dir = _make_fake_scripts_dir(tmp_path)
    monkeypatch.setattr(B, "_SCRIPTS_DIR", fake_scripts_dir)

    rc = B.main(["--kb-yaml", str(kb_path), "--all"])
    # rc=1 because the episode failed, but the lock WAS acquired
    assert rc == 1
    assert acquired_with.get("command") == "backfill-index"
    assert acquired_with.get("project_root") == tmp_path


def test_backfill_fails_when_lock_held(tmp_path, monkeypatch):
    """Pre-written live-PID lock → LockBusyError → exit code 1."""
    # Must have at least one published episode so the lock path is reached.
    published_ep = {"id": 1, "status": "published", "audio": "ep1.mp3", "topic": "test", "date": "2026-01-01"}
    _make_episodes_yaml(tmp_path, episodes=[published_ep], filename="episodes.yaml")
    kb_path = _make_kb_yaml(tmp_path, shows=[_show_dict()])

    # Write a lock file claiming to be held by our own (live) PID
    lock_path = tmp_path / LOCK_FILENAME
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "command": "other-cmd", "start_time": 0.0}),
        encoding="utf-8",
    )

    fake_scripts_dir = _make_fake_scripts_dir(tmp_path)
    monkeypatch.setattr(B, "_SCRIPTS_DIR", fake_scripts_dir)

    # Use a very short timeout so the test doesn't hang
    import lock as L
    original_lock = L.kb_mutation_lock

    from contextlib import contextmanager

    @contextmanager
    def fast_lock(project_root, command, *, timeout=5.0):
        with original_lock(project_root, command, timeout=0.05):
            yield

    monkeypatch.setattr(B, "kb_mutation_lock", fast_lock)

    rc = B.main(["--kb-yaml", str(kb_path), "--all"])
    assert rc == 1
