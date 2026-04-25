"""Dual-format state file loader for .notebooklm-state.yaml.

Reads both the legacy flat format and the new shows-scoped format;
always writes the new format. Also provides idle-check helpers used
by the migrator and detached background agents.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def load_state_file(path: Path, *, default_show_id: str) -> dict:
    """Load state file; return dict with top-level `shows` key.

    If the file is in legacy format (top-level `runs`/`notebooks`/`last_*`),
    the loader wraps those under `shows.<default_show_id>.*`. If already
    new format (top-level `shows:`), returns as-is.

    Missing file returns `{"shows": {}}`.
    """
    if not path.exists():
        return {"shows": {}}

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} does not contain a dict")

    if "shows" in raw:
        # New format — ensure every show's state has runs/notebooks keys
        shows = raw.get("shows") or {}
        for sid, show_state in shows.items():
            show_state.setdefault("runs", [])
            show_state.setdefault("notebooks", [])
        return {"shows": shows}

    # Legacy: wrap top-level keys under shows.<default_show_id>
    return {
        "shows": {
            default_show_id: {
                "last_podcast": raw.get("last_podcast"),
                "last_digest": raw.get("last_digest"),
                "last_quiz": raw.get("last_quiz"),
                "notebooks": raw.get("notebooks") or [],
                "runs": raw.get("runs") or [],
            }
        }
    }


def write_state_file(path: Path, state: dict) -> None:
    """Always write new format. Atomic via temp + os.replace."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(path.parent), delete=False,
        prefix=path.name + ".", suffix=".tmp", encoding="utf-8",
    )
    try:
        yaml.safe_dump(state, tmp, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def find_pending_runs(state: dict) -> list[dict]:
    """Return every run entry with status=pending across all shows."""
    pending = []
    for sid, show_state in (state.get("shows") or {}).items():
        for run in (show_state.get("runs") or []):
            if run.get("status") == "pending":
                pending.append({"show": sid, **run})
    return pending


def find_pending_notebooks(state: dict) -> list[dict]:
    """Return every notebook entry with status=pending across all shows."""
    pending = []
    for sid, show_state in (state.get("shows") or {}).items():
        for nb in (show_state.get("notebooks") or []):
            if nb.get("status") == "pending":
                pending.append({"show": sid, **nb})
    return pending


class PendingWorkError(RuntimeError):
    """Idle-check found pending runs or notebooks; migration refused."""
