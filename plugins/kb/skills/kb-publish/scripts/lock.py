"""KB-wide mutation file lock. Acquired by every mutating command
(kb-notebooklm, kb-publish, backfill-index, migrate) before writing
any state/sidecar/output file. Includes detached background agents.
"""
from __future__ import annotations

import errno
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path


LOCK_FILENAME = ".kb-mutation.lock"


class LockBusyError(RuntimeError):
    """Lock is held by another live process."""


def _is_alive(pid: int) -> bool:
    """Check if a PID is alive via os.kill(pid, 0)."""
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno != errno.ESRCH  # ESRCH = no such process
    return True


def _confirm_remove_stale(lock_info: dict) -> bool:
    """Ask user whether to remove a stale lock file. Monkeypatched in tests."""
    prompt = (
        f"\nStale .kb-mutation.lock found (pid={lock_info.get('pid')}, "
        f"command={lock_info.get('command')!r}, "
        f"started={lock_info.get('start_time')}). "
        f"Remove it? [y/N] "
    )
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        resp = input().strip().lower()
    except EOFError:
        return False
    return resp in ("y", "yes")


@contextmanager
def kb_mutation_lock(project_root: Path, command: str, *, timeout: float = 5.0):
    """Acquire .kb-mutation.lock; raise LockBusyError on timeout or if held
    by another live process.

    On acquisition, writes {pid, command, start_time} to the lock file.
    Released on normal exit, exception, SIGINT, or SIGTERM.
    """
    lock_path = project_root / LOCK_FILENAME
    deadline = time.monotonic() + timeout

    while True:
        try:
            # O_EXCL + O_CREAT = atomic create-if-not-exists
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, json.dumps({
                    "pid": os.getpid(),
                    "command": command,
                    "start_time": time.time(),
                }).encode())
            finally:
                os.close(fd)
            break
        except FileExistsError:
            # Lock exists — is it stale?
            try:
                info = json.loads(lock_path.read_text())
                owner_pid = info.get("pid")
            except (OSError, ValueError, json.JSONDecodeError):
                # Corrupted lock file — treat as stale
                info = {"pid": 0, "command": "<unreadable>"}
                owner_pid = 0

            if owner_pid and _is_alive(owner_pid):
                # Still held by a live process
                if time.monotonic() >= deadline:
                    raise LockBusyError(
                        f"{lock_path} held by pid={owner_pid} "
                        f"command={info.get('command')!r}"
                    )
                time.sleep(0.1)
                continue

            # Stale lock — ask the user (test can monkeypatch)
            if _confirm_remove_stale(info):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass  # another process got there first; loop around
            else:
                raise LockBusyError(
                    f"stale lock at {lock_path} (pid={owner_pid}) not removed"
                )

    # Install signal handlers to release on SIGINT/SIGTERM
    prev_sigint = signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    prev_sigterm = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
