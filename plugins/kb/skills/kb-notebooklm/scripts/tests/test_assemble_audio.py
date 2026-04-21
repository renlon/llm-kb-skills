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
