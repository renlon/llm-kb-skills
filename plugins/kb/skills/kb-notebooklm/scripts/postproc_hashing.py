"""Deterministic hashing and completeness helpers for kb-notebooklm post-processing.

These helpers give the skill's dedup logic a stable, testable representation of
what's been done and what settings it was done with. See
`docs/superpowers/specs/2026-04-20-podcast-intro-hosts-transcript-design.md`
sections 6 and 7 for the semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def params_hash(
    *,
    format: str,
    length: str,
    language: str,
    rendered_prompt: str,
    host_pool: list[str],
) -> str:
    """Hash of prompt-affecting generation settings.

    Changes here force NotebookLM regeneration.
    """
    parts = [
        format,
        length,
        language,
        _sha256_hex(rendered_prompt),
        json.dumps(host_pool[:2], ensure_ascii=False, sort_keys=False),
    ]
    return _sha256_hex("\x1f".join(parts))


def postproc_hash(
    *,
    intro_music_path: str | None,
    intro_music_mtime: float | None,
    intro_music_size: int | None,
    intro_music_content_sha256: str | None,
    requested_intro_length: float,
    requested_crossfade_seconds: float,
    effective_intro_length: float,
    effective_crossfade: float,
    transcript_enabled: bool,
    transcript_model: str,
    transcript_language: str,
    host_pool: list[str],
) -> str:
    """Hash of post-processing settings.

    Changes here mean we can re-run post-processing only (assembly + transcription),
    without hitting NotebookLM again.
    """
    def _str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            # Fixed-precision avoids tiny-FP drift between runs.
            return f"{value:.6f}"
        return str(value)

    parts = [
        _str(intro_music_path),
        _str(intro_music_mtime),
        _str(intro_music_size),
        _str(intro_music_content_sha256),
        _str(requested_intro_length),
        _str(requested_crossfade_seconds),
        _str(effective_intro_length),
        _str(effective_crossfade),
        _str(transcript_enabled),
        _str(transcript_model),
        _str(transcript_language),
        json.dumps(host_pool, ensure_ascii=False, sort_keys=False),
    ]
    return _sha256_hex("\x1f".join(parts))


def hash_intro_file(path: str | os.PathLike[str]) -> tuple[float, int, str]:
    """Return (mtime, size, sha256_hex) for an intro file. Raises FileNotFoundError if missing."""
    p = Path(path)
    stat = p.stat()
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return (stat.st_mtime, stat.st_size, h.hexdigest())


def postproc_complete(
    outputs: Mapping[str, Any],
    *,
    intro_music_configured: bool,
    transcript_enabled: bool,
) -> bool:
    """Return True iff the stored run outputs satisfy the configured features.

    `outputs` is a dict with keys: raw_audio, final_audio, vtt, transcript_md,
    manifest, intro_applied, transcript_applied. `manifest` is transient
    (kb-publish deletes it after consumption) and is explicitly excluded from
    existence checks.
    """
    final = outputs.get("final_audio")
    if not final or not Path(final).exists():
        return False

    if intro_music_configured and not bool(outputs.get("intro_applied")):
        return False

    if transcript_enabled:
        if not bool(outputs.get("transcript_applied")):
            return False
        vtt = outputs.get("vtt")
        md = outputs.get("transcript_md")
        if not vtt or not Path(vtt).exists():
            return False
        if not md or not Path(md).exists():
            return False

    return True
