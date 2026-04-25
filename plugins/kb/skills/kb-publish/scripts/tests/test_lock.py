"""Tests for lock.py — KB-wide mutation file lock."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import lock as L


def test_lock_acquires_and_releases(tmp_path: Path):
    lock_path = tmp_path / ".kb-mutation.lock"
    assert not lock_path.exists()
    with L.kb_mutation_lock(tmp_path, "test-cmd"):
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())
        assert data["command"] == "test-cmd"
        assert data["pid"] == os.getpid()
    assert not lock_path.exists()


def test_lock_releases_on_exception(tmp_path: Path):
    lock_path = tmp_path / ".kb-mutation.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with L.kb_mutation_lock(tmp_path, "test-cmd"):
            raise RuntimeError("boom")
    assert not lock_path.exists()


def test_lock_raises_when_held_by_live_process(tmp_path: Path):
    """Simulate another live process holding the lock."""
    lock_path = tmp_path / ".kb-mutation.lock"
    # Write a lock file claiming to be held by our own process (safe since os.kill(pid, 0) succeeds)
    lock_path.write_text(json.dumps({
        "pid": os.getpid(),
        "command": "other",
        "start_time": time.time(),
    }))
    with pytest.raises(L.LockBusyError, match="held by"):
        with L.kb_mutation_lock(tmp_path, "test-cmd", timeout=0.1):
            pass
    # Lock file is NOT removed when we refuse to acquire (it belongs to the other owner).
    assert lock_path.exists()


def test_lock_removes_stale_lock(tmp_path: Path, monkeypatch):
    """When the lock is owned by a dead PID, it's removed (with monkeypatched confirm)."""
    lock_path = tmp_path / ".kb-mutation.lock"
    # Pick a PID very unlikely to exist
    dead_pid = 999999
    lock_path.write_text(json.dumps({
        "pid": dead_pid,
        "command": "old",
        "start_time": time.time(),
    }))
    # Monkeypatch confirm → yes
    monkeypatch.setattr(L, "_confirm_remove_stale", lambda _: True)
    with L.kb_mutation_lock(tmp_path, "test-cmd"):
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())
        assert data["command"] == "test-cmd"
    assert not lock_path.exists()


def test_lock_refuses_stale_removal_when_user_declines(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / ".kb-mutation.lock"
    lock_path.write_text(json.dumps({"pid": 999999, "command": "old", "start_time": 0}))
    monkeypatch.setattr(L, "_confirm_remove_stale", lambda _: False)
    with pytest.raises(L.LockBusyError):
        with L.kb_mutation_lock(tmp_path, "test-cmd", timeout=0.1):
            pass
