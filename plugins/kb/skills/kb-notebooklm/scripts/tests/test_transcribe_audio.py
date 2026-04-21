"""Tests for transcribe_audio.py — timestamp formatting, VTT escaping, speaker labeling."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import transcribe_audio as T  # noqa: E402


# ------------------------------
# Timestamp formatting
# ------------------------------

def test_format_timestamp_zero():
    assert T.format_timestamp(0.0) == "00:00:00.000"


def test_format_timestamp_sub_second():
    assert T.format_timestamp(0.24) == "00:00:00.240"


def test_format_timestamp_seconds():
    assert T.format_timestamp(65.5) == "00:01:05.500"


def test_format_timestamp_crosses_hour():
    assert T.format_timestamp(3609.1) == "01:00:09.100"


def test_format_timestamp_applies_offset():
    assert T.format_timestamp(0.24, offset=9.0) == "00:00:09.240"


def test_format_timestamp_applies_offset_crossing_minute():
    assert T.format_timestamp(55.5, offset=9.0) == "00:01:04.500"


# ------------------------------
# VTT escaping
# ------------------------------

def test_vtt_escape_lt_gt_amp():
    assert T.escape_vtt_text("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_vtt_escape_preserves_cjk():
    # No special characters in CJK — pass through.
    assert T.escape_vtt_text("瓜瓜龙你好") == "瓜瓜龙你好"


def test_vtt_voice_tag_escapes_angle_brackets_in_speaker_name():
    # Defensive: if a speaker name somehow contains <, it must not break the voice tag.
    assert T.voice_tag("Weird<Name>", "hello") == "<v Weird&lt;Name&gt;>hello"


def test_vtt_voice_tag_normal_case():
    assert T.voice_tag("瓜瓜龙", "大家好") == "<v 瓜瓜龙>大家好"


# ------------------------------
# Align words to speakers
# ------------------------------

def test_align_words_single_speaker(fake_whisper_segment, fake_diarization_turn):
    seg = fake_whisper_segment(0.0, 4.0, "hello world how are you")
    turns = [fake_diarization_turn(0.0, 4.0, "SPEAKER_00")]
    subs = T.split_segment_by_diarization(seg, turns)
    # All words in one speaker → one sub-segment.
    assert len(subs) == 1
    assert subs[0]["speaker"] == "SPEAKER_00"
    assert subs[0]["text"].startswith("hello")
    assert subs[0]["start"] == pytest.approx(0.0, abs=0.01)
    assert subs[0]["end"] == pytest.approx(4.0, abs=0.01)


def test_align_words_splits_at_diarization_boundary(fake_whisper_segment, fake_diarization_turn):
    """A single whisper segment whose words span two turns must split into two subs."""
    seg = fake_whisper_segment(0.0, 4.0, "hello world how are you")
    # Turn boundary at 2.0: SPEAKER_00 [0..2], SPEAKER_01 [2..4].
    turns = [
        fake_diarization_turn(0.0, 2.0, "SPEAKER_00"),
        fake_diarization_turn(2.0, 4.0, "SPEAKER_01"),
    ]
    subs = T.split_segment_by_diarization(seg, turns)
    assert len(subs) == 2
    assert subs[0]["speaker"] == "SPEAKER_00"
    assert subs[1]["speaker"] == "SPEAKER_01"
    # Words split: "hello world" went to first, "how are you" to second.
    assert "hello" in subs[0]["text"]
    assert "how" in subs[1]["text"]


def test_align_words_assigns_uncovered_words_to_most_recent_speaker(fake_whisper_segment, fake_diarization_turn):
    """If the diarization turn ends before the segment does, trailing words go to the most recent speaker."""
    seg = fake_whisper_segment(0.0, 4.0, "hello world silence tail")
    turns = [fake_diarization_turn(0.0, 2.0, "SPEAKER_00")]  # no coverage for 2..4
    subs = T.split_segment_by_diarization(seg, turns)
    assert len(subs) >= 1
    # All words still get labeled — trailing assigned to SPEAKER_00 (the last known speaker).
    speakers = {sub["speaker"] for sub in subs}
    assert speakers == {"SPEAKER_00"}


# ------------------------------
# Host-pool mapping (first-appearance ordering)
# ------------------------------

def test_map_speakers_to_hosts_by_first_appearance():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01", "text": "hi"},
        {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "hello"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_01", "text": "there"},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    # SPEAKER_01 appeared first → 瓜瓜龙, SPEAKER_00 → 海发菜
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert mapped[2]["speaker"] == "瓜瓜龙"


def test_map_speakers_overflow_synthesizes_guest_names():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "A", "text": "a"},
        {"start": 1.0, "end": 2.0, "speaker": "B", "text": "b"},
        {"start": 2.0, "end": 3.0, "speaker": "C", "text": "c"},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]  # pool exhausted at speaker 3
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert mapped[2]["speaker"] == "嘉宾A"


def test_self_intro_swap_triggers_when_ordering_is_wrong():
    """If speaker_00's first line says '我是海发菜' (not 瓜瓜龙), swap the mapping."""
    subs = [
        # Fake data: the speaker that appears first is SAYING the other host's name.
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "我是海发菜, 欢迎收听."},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "我是瓜瓜龙, 今天要聊 KV Cache."},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    # After swap: SPEAKER_00 → 海发菜 (because it says "我是海发菜")
    assert mapped[0]["speaker"] == "海发菜"
    assert mapped[1]["speaker"] == "瓜瓜龙"
    assert any("swap" in w.lower() for w in warnings)


def test_self_intro_does_not_swap_when_ordering_is_correct():
    subs = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "我是瓜瓜龙, 欢迎收听."},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "我是海发菜, 今天我们聊."},
    ]
    host_pool = ["瓜瓜龙", "海发菜"]
    mapped, warnings = T.map_speakers_to_hosts(subs, host_pool)
    assert mapped[0]["speaker"] == "瓜瓜龙"
    assert mapped[1]["speaker"] == "海发菜"
    assert not any("swap" in w.lower() for w in warnings)


# ------------------------------
# Render outputs
# ------------------------------

def test_render_vtt_zero_offset():
    subs = [
        {"start": 0.24, "end": 4.12, "speaker": "瓜瓜龙", "text": "大家好."},
        {"start": 4.12, "end": 9.56, "speaker": "海发菜", "text": "今天聊 KV Cache."},
    ]
    vtt = T.render_vtt(subs, offset=0.0)
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:00.240 --> 00:00:04.120" in vtt
    assert "<v 瓜瓜龙>大家好." in vtt
    assert "00:00:04.120 --> 00:00:09.560" in vtt
    assert "<v 海发菜>今天聊 KV Cache." in vtt


def test_render_vtt_with_offset():
    subs = [{"start": 0.24, "end": 4.12, "speaker": "瓜瓜龙", "text": "大家好."}]
    vtt = T.render_vtt(subs, offset=9.0)
    assert "00:00:09.240 --> 00:00:13.120" in vtt


def test_render_markdown_merges_consecutive_same_speaker():
    subs = [
        {"start": 0.0, "end": 1.0, "speaker": "瓜瓜龙", "text": "大家好."},
        {"start": 1.0, "end": 2.0, "speaker": "瓜瓜龙", "text": "今天聊 KV Cache."},
        {"start": 2.0, "end": 3.0, "speaker": "海发菜", "text": "好的."},
    ]
    md = T.render_markdown(subs, title="全栈AI — KV Cache (2026-04-20)")
    assert md.startswith("# 全栈AI — KV Cache (2026-04-20)\n")
    # Consecutive 瓜瓜龙 segments merged with a space.
    assert "**瓜瓜龙:** 大家好. 今天聊 KV Cache." in md
    # Speaker change → new paragraph.
    assert "**海发菜:** 好的." in md


def test_derive_title_from_filename():
    assert T.derive_title("podcast-kv-cache-2026-04-20.raw.mp3") == "全栈AI — kv-cache (2026-04-20)"
    assert T.derive_title("podcast-attention-2026-05-12.mp3") == "全栈AI — attention (2026-05-12)"


def test_derive_title_falls_back_to_basename_when_pattern_mismatched():
    # Unrecognized pattern → fall back to cleanup-only.
    assert T.derive_title("strange-name.wav").startswith("全栈AI — ")


# ------------------------------
# JSON output shape
# ------------------------------

def test_json_success_shape():
    obj = T.build_result_json(
        success=True, vtt="/tmp/x.vtt", markdown="/tmp/x.md",
        speaker_count=2, duration_seconds=1200.5,
        warnings=[], error=None,
    )
    assert obj["success"] is True
    assert obj["vtt"] == "/tmp/x.vtt"
    assert obj["markdown"] == "/tmp/x.md"
    assert obj["speaker_count"] == 2
    assert obj["error"] is None


def test_json_failure_shape():
    obj = T.build_result_json(
        success=False, vtt=None, markdown=None,
        speaker_count=0, duration_seconds=None,
        warnings=["HUGGINGFACE_TOKEN not set"],
        error="missing_hf_token",
    )
    assert obj["success"] is False
    assert obj["vtt"] is None
    assert obj["error"] == "missing_hf_token"
