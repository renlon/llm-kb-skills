"""Shared pytest fixtures for kb-notebooklm script tests.

Synthetic whisper/diarization data and helpers for generating test audio files.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def ffmpeg_required():
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not on PATH")


@pytest.fixture
def silent_wav(tmp_path: Path, ffmpeg_required) -> Path:
    """Generate a 3-second silent WAV for ffprobe duration tests."""
    out = tmp_path / "silent_3s.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "3", str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def silent_wav_factory(tmp_path: Path, ffmpeg_required):
    """Factory for generating silent WAVs of arbitrary durations."""
    def _make(seconds: float, name: str = "silent.wav") -> Path:
        out = tmp_path / name
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", str(seconds), str(out),
            ],
            check=True,
        )
        return out
    return _make


@pytest.fixture
def fake_whisper_segment():
    """Build a whisper-like segment dict for alignment tests."""
    def _make(start: float, end: float, text: str, words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if words is None:
            # Evenly distribute words across the segment window.
            tokens = text.split()
            if not tokens:
                tokens = [text]
            step = (end - start) / len(tokens)
            words = [
                {"start": start + i * step, "end": start + (i + 1) * step, "word": tok}
                for i, tok in enumerate(tokens)
            ]
        return {"start": start, "end": end, "text": text, "words": words}
    return _make


@pytest.fixture
def fake_diarization_turn():
    """Build a diarization turn dict for alignment tests."""
    def _make(start: float, end: float, speaker: str) -> dict[str, Any]:
        return {"start": start, "end": end, "speaker": speaker}
    return _make
