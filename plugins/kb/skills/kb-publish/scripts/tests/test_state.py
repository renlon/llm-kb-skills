"""Tests for state.py — dual-format .notebooklm-state.yaml loader."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import state as ST


def _write_legacy_state(path: Path, runs: list[dict] = None, notebooks: list[dict] = None):
    data = {
        "last_podcast": None,
        "last_digest": None,
        "last_quiz": None,
        "notebooks": notebooks or [],
        "runs": runs or [],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _write_new_state(path: Path, shows_data: dict):
    data = {"shows": shows_data}
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_load_state_legacy_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"workflow": "podcast", "status": "completed"}])
    state = ST.load_state_file(p, default_show_id="quanzhan-ai")
    # Legacy → wrap under shows.<default-show-id>
    assert "shows" in state
    assert "quanzhan-ai" in state["shows"]
    assert state["shows"]["quanzhan-ai"]["runs"][0]["workflow"] == "podcast"
    assert state["shows"]["quanzhan-ai"]["last_podcast"] is None


def test_load_state_new_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "quanzhan-ai": {
            "last_podcast": None,
            "notebooks": [{"id": "nb1"}],
            "runs": [],
        }
    })
    state = ST.load_state_file(p, default_show_id="unused")
    assert state["shows"]["quanzhan-ai"]["notebooks"][0]["id"] == "nb1"


def test_load_state_missing_file_returns_empty(tmp_path: Path):
    p = tmp_path / "missing.yaml"
    state = ST.load_state_file(p, default_show_id="quanzhan-ai")
    assert state == {"shows": {}}


def test_write_state_always_new_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    state = {"shows": {"a": {"runs": [{"x": 1}]}}}
    ST.write_state_file(p, state)
    parsed = yaml.safe_load(p.read_text())
    assert "shows" in parsed
    assert "last_podcast" not in parsed  # no legacy top-level keys


def test_roundtrip_legacy_to_new(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"w": "podcast"}])
    state = ST.load_state_file(p, default_show_id="show-a")
    ST.write_state_file(p, state)
    # Now re-load: should still succeed as new format
    state2 = ST.load_state_file(p, default_show_id="show-a")
    assert state2["shows"]["show-a"]["runs"][0]["w"] == "podcast"
    # And the file now has `shows:` at top
    parsed = yaml.safe_load(p.read_text())
    assert "shows" in parsed
    assert "runs" not in parsed  # old flat key gone


def test_idle_check_finds_pending_runs_legacy(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"status": "pending", "workflow": "podcast"}])
    state = ST.load_state_file(p, default_show_id="x")
    pending = ST.find_pending_runs(state)
    assert len(pending) == 1
    assert pending[0]["workflow"] == "podcast"


def test_idle_check_finds_pending_notebooks_across_shows(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "show-a": {"notebooks": [{"id": "nb1", "status": "pending"}], "runs": []},
        "show-b": {"notebooks": [], "runs": [{"workflow": "quiz", "status": "pending"}]},
    })
    state = ST.load_state_file(p, default_show_id="x")
    pending_nb = ST.find_pending_notebooks(state)
    pending_runs = ST.find_pending_runs(state)
    assert len(pending_nb) == 1
    assert len(pending_runs) == 1


def test_idle_check_returns_empty_when_idle(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "show-a": {"notebooks": [], "runs": [{"status": "completed"}]},
    })
    state = ST.load_state_file(p, default_show_id="x")
    assert ST.find_pending_runs(state) == []
    assert ST.find_pending_notebooks(state) == []


def test_pending_work_error_exists():
    """PendingWorkError is defined and inherits from RuntimeError."""
    assert issubclass(ST.PendingWorkError, RuntimeError)
