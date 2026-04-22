"""Smoke tests for backfill_index.py — file-resolution helpers only.

The end-to-end flow is integration-tested via the live backfill of EP1+EP2
(Task 11 of the implementation plan).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import backfill_index as B


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
