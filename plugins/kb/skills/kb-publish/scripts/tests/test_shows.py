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


# ------------------------------
# EpRef
# ------------------------------

def test_epref_from_dict_valid():
    r = S.EpRef.from_dict({"show": "quanzhan-ai", "ep": 3})
    assert r.show == "quanzhan-ai"
    assert r.ep == 3


def test_epref_from_dict_raises_on_missing_fields():
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a"})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"ep": 1})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({})


def test_epref_from_dict_raises_on_wrong_types():
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": 123, "ep": 1})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a", "ep": "not-a-number"})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a", "ep": 0})  # ep must be >= 1


def test_epref_from_legacy_str():
    r = S.EpRef.from_legacy("ep-3", default_show="quanzhan-ai")
    assert r.show == "quanzhan-ai" and r.ep == 3


def test_epref_from_legacy_bare_int():
    r = S.EpRef.from_legacy(5, default_show="my-show")
    assert r.show == "my-show" and r.ep == 5


def test_epref_from_legacy_rejects_bad_str():
    with pytest.raises(ValueError):
        S.EpRef.from_legacy("episode-3", default_show="x")
    with pytest.raises(ValueError):
        S.EpRef.from_legacy("ep-notanum", default_show="x")


def test_epref_to_dict_roundtrip():
    r = S.EpRef(show="a", ep=2)
    assert r.to_dict() == {"show": "a", "ep": 2}
    r2 = S.EpRef.from_dict(r.to_dict())
    assert r == r2


def test_epref_wikilink_stem():
    r = S.EpRef(show="quanzhan-ai", ep=3)
    assert r.wikilink_stem("kv-cache") == "wiki/episodes/quanzhan-ai/ep-3-kv-cache"


def test_parse_ep_ref_field_valid():
    r = S.parse_ep_ref_field({"show": "quanzhan-ai", "ep": 1}, known_shows={"quanzhan-ai"})
    assert r.show == "quanzhan-ai" and r.ep == 1


def test_parse_ep_ref_field_rejects_legacy_str():
    with pytest.raises(S.MigrationRequiredError):
        S.parse_ep_ref_field("ep-1", known_shows={"quanzhan-ai"})


def test_parse_ep_ref_field_rejects_legacy_int():
    with pytest.raises(S.MigrationRequiredError):
        S.parse_ep_ref_field(1, known_shows={"quanzhan-ai"})


def test_parse_ep_ref_field_raises_on_unknown_show():
    with pytest.raises(S.UnknownShowError):
        S.parse_ep_ref_field({"show": "other", "ep": 1}, known_shows={"quanzhan-ai"})


# ------------------------------
# Resolvers
# ------------------------------

def _make_shows(ids: list[str]) -> list[S.Show]:
    """Helper to build real Show objects for resolver tests."""
    shows = []
    for i, sid in enumerate(ids):
        shows.append(S.Show(
            id=sid, title=sid.title(), description="",
            default=False, language="zh_Hans",
            hosts=["A", "B"], extra_host_names=[],
            intro_music=None,
            intro_music_length_seconds=12, intro_crossfade_seconds=3,
            podcast_format="deep-dive", podcast_length="long",
            transcript={"enabled": False, "model": "", "device": "auto", "language": "zh"},
            episodes_registry=f"episodes-{sid}.yaml" if i > 0 else "episodes.yaml",
            wiki_episodes_dir=f"episodes/{sid}",
            xiaoyuzhou={},
        ))
    return shows


def test_resolve_mutation_single_show_implicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_mutation(shows, None).id == "a"


def test_resolve_mutation_single_show_explicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_mutation(shows, "a").id == "a"


def test_resolve_mutation_single_show_unknown_id():
    shows = _make_shows(["a"])
    with pytest.raises(S.ShowNotFoundError):
        S.resolve_show_for_mutation(shows, "other")


def test_resolve_mutation_multi_show_no_flag_is_error():
    shows = _make_shows(["a", "b"])
    with pytest.raises(S.AmbiguousShowError):
        S.resolve_show_for_mutation(shows, None)


def test_resolve_mutation_multi_show_explicit_selects():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_mutation(shows, "b").id == "b"


def test_resolve_read_single_show_implicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_read(shows, None).id == "a"


def test_resolve_read_multi_show_no_flag_returns_none():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_read(shows, None) is None


def test_resolve_read_multi_show_explicit_selects():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_read(shows, "a").id == "a"


def test_resolve_read_single_show_unknown_id():
    shows = _make_shows(["a"])
    with pytest.raises(S.ShowNotFoundError):
        S.resolve_show_for_read(shows, "other")


def test_epref_rejects_bool_ep():
    with pytest.raises(ValueError):
        S.EpRef(show="x", ep=True)


def test_epref_from_dict_rejects_bool_ep():
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "x", "ep": True})


def test_epref_from_legacy_rejects_bool():
    with pytest.raises(ValueError):
        S.EpRef.from_legacy(True, default_show="x")


def test_epref_from_legacy_rejects_zero_int():
    with pytest.raises(ValueError):
        S.EpRef.from_legacy(0, default_show="x")
