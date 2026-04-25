"""Tests for shows.py — Show dataclass, EpRef, resolvers, validators."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shows as S


# ------------------------------
# Show dataclass + validate_shows
# ------------------------------

def _valid_show_dict(show_id: str = "quanzhan-ai") -> dict:
    return {
        "id": show_id,
        "title": "全栈AI",
        "description": "Test",
        "language": "zh_Hans",
        "hosts": ["A", "B"],
        "extra_host_names": [],
        "intro_music": "/dev/null/intro.mp3",
        "intro_music_length_seconds": 12,
        "intro_crossfade_seconds": 3,
        "podcast_format": "deep-dive",
        "podcast_length": "long",
        "transcript": {"enabled": True, "model": "large-v3", "device": "auto", "language": "zh"},
        "episodes_registry": "episodes.yaml",
        "wiki_episodes_dir": f"episodes/{show_id}",
        # podcast_id parameterized on show_id so multi-show fixtures don't
        # incidentally trip the uniqueness check.
        "xiaoyuzhou": {"podcast_id": f"pod-{show_id}"},
    }


def test_validate_shows_accepts_single_valid_show(tmp_path: Path):
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    shows = S.validate_shows([_valid_show_dict()], project_root=tmp_path, wiki_path=wiki_path)
    assert len(shows) == 1
    assert shows[0].id == "quanzhan-ai"
    assert shows[0].wiki_episodes_dir == "episodes/quanzhan-ai"


def test_validate_shows_rejects_empty_list(tmp_path: Path):
    with pytest.raises(S.ShowConfigError, match="at least one"):
        S.validate_shows([], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_duplicate_id(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    # Two shows with same id
    s1 = _valid_show_dict("show-a")
    s2 = _valid_show_dict("show-a")
    # Make their registry paths and wiki_episodes_dir different so that's not the failure reason
    s2["episodes_registry"] = "episodes-2.yaml"
    s2["wiki_episodes_dir"] = "episodes/show-a"  # same dir — will collide too
    with pytest.raises(S.ShowConfigError, match="duplicate"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_bad_id_format(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("Invalid_ID")
    with pytest.raises(S.ShowConfigError, match="id.*pattern"):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_non_conventional_wiki_episodes_dir(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("show-a")
    bad["wiki_episodes_dir"] = "custom/path"  # not episodes/<id>
    with pytest.raises(S.ShowConfigError, match="wiki_episodes_dir"):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_escape_in_wiki_episodes_dir(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("show-a")
    bad["wiki_episodes_dir"] = "../escape"
    with pytest.raises(S.ShowConfigError):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_multiple_defaults(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s1["default"] = True
    s1["episodes_registry"] = "episodes-a.yaml"
    s2 = _valid_show_dict("b")
    s2["default"] = True
    s2["episodes_registry"] = "episodes-b.yaml"
    with pytest.raises(S.ShowConfigError, match="one show.*default"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_allows_zero_defaults(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s1["episodes_registry"] = "episodes-a.yaml"
    s2 = _valid_show_dict("b")
    s2["episodes_registry"] = "episodes-b.yaml"
    shows = S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")
    assert len(shows) == 2


def test_validate_shows_rejects_duplicate_episodes_registry(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s2 = _valid_show_dict("b")
    # Both use "episodes.yaml" (default)
    with pytest.raises(S.ShowConfigError, match="episodes_registry.*duplicate"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_load_shows_reads_from_kb_yaml(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    kb = {
        "integrations": {
            "notebooklm": {"wiki_path": str(tmp_path / "wiki")},
            "shows": [_valid_show_dict()],
        }
    }
    shows = S.load_shows(kb, project_root=tmp_path)
    assert len(shows) == 1
    assert shows[0].id == "quanzhan-ai"


def test_load_shows_raises_when_missing(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    kb = {"integrations": {"notebooklm": {"wiki_path": str(tmp_path / "wiki")}}}
    with pytest.raises(S.ShowConfigError):
        S.load_shows(kb, project_root=tmp_path)
