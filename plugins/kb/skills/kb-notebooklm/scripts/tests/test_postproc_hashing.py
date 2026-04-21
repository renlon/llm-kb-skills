"""Tests for postproc_hashing: params_hash, postproc_hash, postproc_complete."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import postproc_hashing as H  # noqa: E402


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
