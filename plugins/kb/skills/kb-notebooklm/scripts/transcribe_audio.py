#!/usr/bin/env python3
"""Transcribe a raw NotebookLM MP3 with faster-whisper + pyannote speaker diarization.

Emits WebVTT (with optional offset so captions align to the final assembled MP3)
and a human-readable markdown transcript.

Exit codes:
  0  success (also emitted when diarization produced only 1 cluster — logged)
  1  invalid CLI arguments
  3  HUGGINGFACE_TOKEN env var missing
  4  model download failed (offline or HF auth issues)
  5  whisper/pyannote runtime error
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Sequence


# ------------------------------
# Pure helpers (no ML deps — safe to import for tests)
# ------------------------------

def format_timestamp(seconds: float, offset: float = 0.0) -> str:
    """Format a timestamp as HH:MM:SS.mmm (WebVTT form)."""
    t = max(0.0, seconds + offset)
    total_ms = int(round(t * 1000))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def escape_vtt_text(text: str) -> str:
    """Minimal HTML/WebVTT escaping — escape & first, then < and >."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def voice_tag(speaker: str, text: str) -> str:
    """Wrap cue body in a WebVTT voice tag. Escapes speaker name defensively."""
    return f"<v {escape_vtt_text(speaker)}>{escape_vtt_text(text)}"


def split_segment_by_diarization(
    segment: dict[str, Any], turns: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Split a whisper segment's words into sub-segments by speaker.

    For each word, look up the diarization turn whose interval covers the word's
    midpoint. Words with no covering turn inherit the most recently seen speaker.
    Consecutive words with the same speaker are merged into one sub-segment.
    """
    words = segment.get("words") or []
    if not words:
        return []

    def _speaker_for_time(t: float, last_speaker: str | None) -> str | None:
        # Use half-open intervals [start, end) so that boundary points (e.g. t==2.0
        # when one turn ends at 2.0 and the next starts at 2.0) go to the LATER turn.
        for turn in turns:
            if turn["start"] <= t < turn["end"]:
                return turn["speaker"]
        # t fell exactly on the last turn's end — assign to that turn's speaker.
        for turn in reversed(turns):
            if t == turn["end"]:
                return turn["speaker"]
        return last_speaker

    last_speaker: str | None = None
    # Bootstrap last_speaker: if the first word's midpoint lands in a turn, great.
    # Otherwise fall back to the first turn's speaker if any.
    if turns:
        last_speaker = turns[0]["speaker"]

    subs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for w in words:
        midpoint = (w["start"] + w["end"]) / 2.0
        sp = _speaker_for_time(midpoint, last_speaker)
        if sp is None:
            sp = last_speaker or "SPEAKER_00"
        last_speaker = sp

        if current is None or current["speaker"] != sp:
            if current is not None:
                subs.append(current)
            current = {
                "start": w["start"],
                "end": w["end"],
                "speaker": sp,
                "text": w["word"].strip(),
            }
        else:
            current["end"] = w["end"]
            # Space-separate tokens. strip() removes leading space from faster-whisper's
            # raw word forms (they typically start with a space).
            current["text"] = (current["text"] + " " + w["word"].strip()).strip()

    if current is not None:
        subs.append(current)

    # Clean doubled spaces from naive joining.
    for s in subs:
        s["text"] = re.sub(r"\s+", " ", s["text"]).strip()

    return subs


def map_speakers_to_hosts(
    sub_segments: Sequence[dict[str, Any]], host_pool: Sequence[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Assign host names to speaker IDs by first-appearance order.

    Applies a best-effort self-intro swap: if the speaker that appears first
    introduces the OTHER host's name (and not its own), swap the mapping.
    Overflow speakers beyond the host pool get synthesized 嘉宾A/B/C labels.
    """
    warnings: list[str] = []
    # First-appearance order of distinct speaker IDs.
    seen: list[str] = []
    for sub in sub_segments:
        sp = sub["speaker"]
        if sp not in seen:
            seen.append(sp)

    # Build initial mapping.
    mapping: dict[str, str] = {}
    for i, sp in enumerate(seen):
        if i < len(host_pool):
            mapping[sp] = host_pool[i]
        else:
            guest_idx = i - len(host_pool)
            mapping[sp] = f"嘉宾{chr(ord('A') + guest_idx)}"

    # Self-intro validation (only makes sense when we have at least 2 hosts and 2 speakers).
    if len(host_pool) >= 2 and len(seen) >= 2:
        def _first_text(speaker_id: str) -> str:
            for s in sub_segments:
                if s["speaker"] == speaker_id:
                    return s["text"]
            return ""

        first_sp = seen[0]
        second_sp = seen[1]
        first_text = _first_text(first_sp)
        second_text = _first_text(second_sp)
        h0, h1 = host_pool[0], host_pool[1]
        # Swap if first speaker says h1 but not h0, AND second speaker says h0 but not h1.
        if (h1 in first_text and h0 not in first_text and
                h0 in second_text and h1 not in second_text):
            mapping[first_sp] = h1
            mapping[second_sp] = h0
            warnings.append(
                f"Self-intro swap: speaker order did not match host pool; "
                f"swapped to {h1}, {h0}."
            )

    mapped = [
        {**sub, "speaker": mapping[sub["speaker"]]}
        for sub in sub_segments
    ]
    return mapped, warnings


def render_vtt(sub_segments: Sequence[dict[str, Any]], offset: float = 0.0) -> str:
    """Render sub-segments as WebVTT text."""
    lines = ["WEBVTT", ""]
    for s in sub_segments:
        start = format_timestamp(s["start"], offset=offset)
        end = format_timestamp(s["end"], offset=offset)
        lines.append(f"{start} --> {end}")
        lines.append(voice_tag(s["speaker"], s["text"]))
        lines.append("")
    return "\n".join(lines)


def render_markdown(sub_segments: Sequence[dict[str, Any]], title: str) -> str:
    """Render sub-segments as markdown, merging consecutive same-speaker turns."""
    paragraphs: list[tuple[str, str]] = []
    for s in sub_segments:
        sp = s["speaker"]
        text = s["text"]
        if paragraphs and paragraphs[-1][0] == sp:
            prev_sp, prev_text = paragraphs[-1]
            paragraphs[-1] = (prev_sp, (prev_text + " " + text).strip())
        else:
            paragraphs.append((sp, text))

    body = "\n\n".join(f"**{sp}:** {text}" for sp, text in paragraphs)
    return f"# {title}\n\n{body}\n"


_FILENAME_PATTERN = re.compile(r"^podcast-(?P<theme>.+)-(?P<date>\d{4}-\d{2}-\d{2})(?:\.raw)?\.(?:mp3|wav|m4a|flac)$", re.IGNORECASE)


def derive_title(filename: str) -> str:
    """Derive an H1 title from a raw audio filename, following the '全栈AI — <theme> (date)' convention."""
    m = _FILENAME_PATTERN.match(Path(filename).name)
    if m:
        return f"全栈AI — {m.group('theme')} ({m.group('date')})"
    # Fallback: strip common suffixes, prefix brand.
    stem = Path(filename).stem
    stem = re.sub(r"\.raw$", "", stem, flags=re.IGNORECASE)
    return f"全栈AI — {stem}"


def build_result_json(
    *,
    success: bool,
    vtt: str | None,
    markdown: str | None,
    speaker_count: int,
    duration_seconds: float | None,
    warnings: list[str],
    error: str | None,
) -> dict[str, Any]:
    return {
        "success": success,
        "vtt": vtt,
        "markdown": markdown,
        "speaker_count": speaker_count,
        "duration_seconds": duration_seconds,
        "warnings": warnings,
        "error": error,
    }


# ------------------------------
# Model-loading seams (integration boundary — stubbed in tests)
# ------------------------------

def resolve_device(requested: str) -> str:
    """Pick a device for faster-whisper.

    `mps` is intentionally NOT offered — faster-whisper doesn't support it.
    Apple Silicon and Intel Macs both run on cpu.
    """
    if requested in ("cpu", "cuda"):
        return requested
    # auto
    if platform.system() == "Darwin":
        return "cpu"
    # On Linux/NVIDIA, best-effort detect CUDA.
    try:
        import ctranslate2  # type: ignore
        if getattr(ctranslate2, "get_cuda_device_count", lambda: 0)() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def transcribe_with_whisper(
    audio_path: str, *, model_name: str, device: str, language: str
) -> tuple[list[dict[str, Any]], float]:
    """Run faster-whisper and return (segments, duration_seconds)."""
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_name, device=device, compute_type="auto")
    segments, info = model.transcribe(
        audio_path, language=language, word_timestamps=True, vad_filter=True,
    )
    out: list[dict[str, Any]] = []
    for s in segments:
        words = [
            {"start": w.start, "end": w.end, "word": w.word}
            for w in (s.words or [])
        ]
        out.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
    return out, float(info.duration)


def diarize_with_pyannote(audio_path: str, *, hf_token: str) -> list[dict[str, Any]]:
    """Run pyannote speaker-diarization-3.1 and return turns."""
    from pyannote.audio import Pipeline  # type: ignore

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    diarization = pipeline(audio_path, num_speakers=2)
    return [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(label)}
        for turn, _, label in diarization.itertracks(yield_label=True)
    ]


# ------------------------------
# CLI
# ------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe + diarize a raw podcast MP3.")
    parser.add_argument("--audio", required=True, help="Path to raw NotebookLM MP3")
    parser.add_argument("--hosts", required=True, help="JSON array of host names, longest pool first")
    parser.add_argument("--output-vtt", required=True, help="Path for WebVTT output")
    parser.add_argument("--output-md", required=True, help="Path for markdown output")
    parser.add_argument("--vtt-offset-seconds", type=float, default=0.0,
                        help="Offset added to all VTT timestamps so captions align to the FINAL MP3.")
    parser.add_argument("--model", default="large-v3", help="faster-whisper model name")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                        help="Inference device (mps not supported)")
    parser.add_argument("--language", default="zh", help="Whisper language hint")
    parser.add_argument("--title", default=None, help="Optional H1 title (else derived from filename)")
    parser.add_argument("--json", action="store_true", help="Emit JSON status to stdout")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    warnings: list[str] = []

    try:
        host_pool = json.loads(args.hosts)
        if not isinstance(host_pool, list) or len(host_pool) < 1:
            raise ValueError("hosts must be a non-empty JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"invalid --hosts: {e}"], error="invalid_hosts",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 1

    hf_token = os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if not hf_token:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=["HUGGINGFACE_TOKEN env var not set. Pyannote requires license acceptance + token — see kb-init setup."],
            error="missing_hf_token",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 3

    device = resolve_device(args.device)

    # Stage 1: transcription
    try:
        whisper_segments, duration = transcribe_with_whisper(
            args.audio, model_name=args.model, device=device, language=args.language,
        )
    except (ImportError, ModuleNotFoundError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"faster-whisper not installed: {e}"], error="module_missing",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 4
    except Exception as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=None,
            warnings=[f"whisper transcription failed: {type(e).__name__}: {e}"], error="whisper_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 5

    # Stage 2: diarization
    try:
        turns = diarize_with_pyannote(args.audio, hf_token=hf_token)
    except (ImportError, ModuleNotFoundError) as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=duration,
            warnings=[f"pyannote.audio not installed: {e}"], error="module_missing",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 4
    except Exception as e:
        payload = build_result_json(
            success=False, vtt=None, markdown=None, speaker_count=0, duration_seconds=duration,
            warnings=[f"pyannote diarization failed: {type(e).__name__}: {e}"], error="pyannote_failed",
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 5

    if not turns:
        warnings.append("Diarization produced no turns — labeling as single speaker.")
        turns = [{"start": 0.0, "end": duration, "speaker": "SPEAKER_00"}]

    # Stage 3: alignment + labeling
    subs: list[dict[str, Any]] = []
    for seg in whisper_segments:
        subs.extend(split_segment_by_diarization(seg, turns))

    mapped, map_warnings = map_speakers_to_hosts(subs, host_pool)
    warnings.extend(map_warnings)

    speaker_count = len({s["speaker"] for s in mapped})
    if speaker_count == 1:
        warnings.append("Only 1 distinct speaker after mapping — diarization may have failed.")

    # Stage 4: render + write
    vtt_text = render_vtt(mapped, offset=args.vtt_offset_seconds)
    title = args.title or derive_title(args.audio)
    md_text = render_markdown(mapped, title=title)

    Path(args.output_vtt).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_vtt).write_text(vtt_text, encoding="utf-8")
    Path(args.output_md).write_text(md_text, encoding="utf-8")

    payload = build_result_json(
        success=True, vtt=args.output_vtt, markdown=args.output_md,
        speaker_count=speaker_count, duration_seconds=duration,
        warnings=warnings, error=None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
