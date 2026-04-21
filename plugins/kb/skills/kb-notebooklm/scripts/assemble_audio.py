#!/usr/bin/env python3
"""Assemble final podcast MP3 from intro music + raw NotebookLM output.

Thin wrapper around `ffmpeg -filter_complex acrossfade`. Performs preflight
on the intro file (clamping intro_length and crossfade to safe values for
short clips), invokes ffmpeg, and emits a structured JSON status line so
the orchestrating skill can read the final offset as a single source of truth.

Exit codes:
  0  success (intro_applied may still be false if config says so)
  1  ffmpeg failed / preflight determined assembly is not possible
  2  invalid CLI arguments
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


# Minimum intro duration we'll even consider (seconds). Below this, skip.
INTRO_FLOOR_SECONDS = 1.5

# Keep at least this much music-only head before the crossfade starts.
MIN_MUSIC_HEAD_SECONDS = 0.5


class ProbeError(RuntimeError):
    """ffprobe could not determine duration."""


@dataclasses.dataclass
class PreflightResult:
    assembly_possible: bool
    effective_intro_length: float
    effective_crossfade: float
    warnings: list[str]


def preflight(
    *, intro_duration: float, requested_intro_length: float, requested_crossfade: float
) -> PreflightResult:
    """Compute effective intro length and crossfade for a given file duration.

    Contract:
      - effective_intro_length = min(requested_intro_length, intro_duration)
      - effective_crossfade    = min(requested_crossfade, effective_intro_length - MIN_MUSIC_HEAD)
      - assembly_possible = intro_duration >= INTRO_FLOOR
    """
    warnings: list[str] = []

    if intro_duration < INTRO_FLOOR_SECONDS:
        warnings.append(
            f"Intro clip duration {intro_duration:.2f}s is below floor "
            f"{INTRO_FLOOR_SECONDS}s — skipping assembly."
        )
        return PreflightResult(False, 0.0, 0.0, warnings)

    effective_intro_length = min(requested_intro_length, intro_duration)
    if effective_intro_length < requested_intro_length:
        warnings.append(
            f"Intro clip shorter than requested ({intro_duration:.2f}s < "
            f"{requested_intro_length}s) — clamped to {effective_intro_length:.2f}s."
        )

    # Keep at least MIN_MUSIC_HEAD_SECONDS of music-only head before the crossfade.
    max_crossfade = max(0.0, effective_intro_length - MIN_MUSIC_HEAD_SECONDS)
    effective_crossfade = min(requested_crossfade, max_crossfade)
    if effective_crossfade < requested_crossfade:
        warnings.append(
            f"Crossfade clamped from {requested_crossfade}s to "
            f"{effective_crossfade:.2f}s to preserve music-only head."
        )

    return PreflightResult(True, effective_intro_length, effective_crossfade, warnings)


def probe_duration(path: str) -> float:
    """Run `ffprobe` to get the duration of an audio file in seconds."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1",
                path,
            ],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise ProbeError(f"ffprobe not on PATH: {e}") from e
    except subprocess.CalledProcessError as e:
        raise ProbeError(f"ffprobe failed: {e.stderr.strip()}") from e

    text = out.stdout.strip()
    if not text:
        raise ProbeError(f"ffprobe returned empty duration for {path}")
    try:
        return float(text)
    except ValueError as e:
        raise ProbeError(f"ffprobe returned non-numeric duration: {text!r}") from e


def build_ffmpeg_argv(
    *,
    intro_path: str,
    raw_path: str,
    output_path: str,
    effective_intro_length: float,
    effective_crossfade: float,
) -> list[str]:
    """Construct the ffmpeg command as an argv list (no shell injection)."""
    # Format floats to stable string form.
    intro_len_s = f"{effective_intro_length}"
    cf_s = f"{effective_crossfade}"
    filter_str = f"[0:a][1:a]acrossfade=d={cf_s}:c1=tri:c2=tri[a]"
    return [
        "ffmpeg", "-y",
        "-t", intro_len_s, "-i", intro_path,
        "-i", raw_path,
        "-filter_complex", filter_str,
        "-map", "[a]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ]


def run_ffmpeg(argv: list[str]) -> tuple[int, str]:
    """Run ffmpeg, return (returncode, stderr_text)."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError as e:
        return (127, f"ffmpeg not on PATH: {e}")
    return (result.returncode, result.stderr)


def build_result_json(
    *,
    success: bool,
    intro_applied: bool,
    output: str | None,
    duration_seconds: float | None,
    effective_intro_length: float,
    effective_crossfade: float,
    warnings: list[str],
    error: str | None,
) -> dict[str, Any]:
    """Assemble the JSON status object. `final_offset_seconds` is authoritative."""
    final_offset = (effective_intro_length - effective_crossfade) if (success and intro_applied) else 0.0
    return {
        "success": success,
        "intro_applied": intro_applied,
        "output": output,
        "duration_seconds": duration_seconds,
        "effective_intro_length": effective_intro_length,
        "effective_crossfade": effective_crossfade,
        "final_offset_seconds": final_offset,
        "warnings": warnings,
        "error": error,
    }


def _final_duration_after_assembly(*, raw_duration: float, effective_intro_length: float, effective_crossfade: float) -> float:
    """Total output duration of the acrossfade graph."""
    return effective_intro_length + raw_duration - effective_crossfade


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble final podcast MP3 with intro crossfade.")
    parser.add_argument("--raw-audio", required=True, help="Path to raw NotebookLM MP3")
    parser.add_argument("--intro", required=True, help="Path to intro music file")
    parser.add_argument("--output", required=True, help="Path for the assembled MP3")
    parser.add_argument("--intro-length", type=float, default=12.0, help="Target intro length in seconds (default 12)")
    parser.add_argument("--crossfade", type=float, default=3.0, help="Crossfade duration in seconds (default 3)")
    parser.add_argument("--json", action="store_true", help="Emit JSON status to stdout")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    warnings: list[str] = []

    # Probe raw audio duration (used for output duration calculation).
    try:
        raw_duration = probe_duration(args.raw_audio)
    except ProbeError as e:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=None,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=[f"Could not probe raw audio: {e}"],
            error="probe_raw_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    # Probe intro duration.
    try:
        intro_duration = probe_duration(args.intro)
    except ProbeError as e:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=[f"Could not probe intro: {e}"],
            error="probe_intro_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    pre = preflight(
        intro_duration=intro_duration,
        requested_intro_length=args.intro_length,
        requested_crossfade=args.crossfade,
    )
    warnings.extend(pre.warnings)

    if not pre.assembly_possible:
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=0.0, effective_crossfade=0.0,
            warnings=warnings,
            error="intro_too_short",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    # Ensure output directory exists.
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    argv_ffmpeg = build_ffmpeg_argv(
        intro_path=args.intro,
        raw_path=args.raw_audio,
        output_path=args.output,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
    )
    rc, stderr = run_ffmpeg(argv_ffmpeg)
    if rc != 0:
        warnings.append(f"ffmpeg exited {rc}: {stderr.strip()[:500]}")
        payload = build_result_json(
            success=False, intro_applied=False, output=None, duration_seconds=raw_duration,
            effective_intro_length=pre.effective_intro_length,
            effective_crossfade=pre.effective_crossfade,
            warnings=warnings,
            error="ffmpeg_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    total_duration = _final_duration_after_assembly(
        raw_duration=raw_duration,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
    )
    payload = build_result_json(
        success=True, intro_applied=True, output=args.output, duration_seconds=total_duration,
        effective_intro_length=pre.effective_intro_length,
        effective_crossfade=pre.effective_crossfade,
        warnings=warnings,
        error=None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
