# Podcast Enhancements: Intro Music, Named Hosts, and Transcripts

**Status:** Design approved (2026-04-20)
**Skill:** `plugins/kb/skills/kb-notebooklm/`
**Related:** `plugins/kb/skills/kb-publish/` (consumes sidecar manifest)

## Problem

The `kb-notebooklm` podcast workflow produces a raw MP3 from Google NotebookLM and delivers it straight to `kb-publish`. Three capabilities are missing:

1. No musical intro — episodes start cold with "Hi 大家好..." and no branding cue.
2. Hosts are anonymous — NotebookLM's default dialogue refers to "the hosts" but they never give themselves names, which breaks the illusion of a recurring two-host show.
3. No transcript is produced — downstream use cases (captions, show-notes, future voice replacement, accessibility) all require a speaker-labeled transcript and none exists today.

A related bug surfaces in the current prompt: it still calls the show "My Lessons Learned" when the on-air brand is **全栈AI**.

## Goals

- Prepend a user-configured intro music clip (10–15s, default 12s) with a 3s crossfade into NotebookLM's podcast audio.
- Have the two hosts introduce themselves by name at the top of every episode. Default names: **瓜瓜龙** (primary explainer) and **海发菜** (primary follow-up asker). Configurable per KB project.
- Produce a speaker-labeled transcript in two formats (WebVTT with timestamps, markdown for humans) alongside the final MP3, using local Whisper + pyannote diarization.
- Fix the "My Lessons Learned" brand leak in the prompt — the on-air brand is **全栈AI**.

## Non-Goals (YAGNI)

Explicitly out of scope for this spec:

- Voice replacement / TTS re-synthesis (would require full re-synthesis of the dialogue).
- AI-generated intro music.
- Outro music bed.
- MP3 chapter markers.
- Per-episode custom host pairs (pool is project-wide).
- Multi-language transcripts per episode (single `language` config per project).
- Uploading the VTT/transcript to 小宇宙 automatically.
- Renaming internal identifiers that contain `MLL` (notebook titles, state keys, staging dir names) — those are dedup/watermark-sensitive.

## Design Overview

The existing podcast background agent already owns "produce the deliverable MP3 for this episode." That agent is extended with two additional stages — **post-process** (crossfade intro music) and **transcribe** (Whisper + pyannote). The raw MP3 from NotebookLM becomes an intermediate artifact; the final deliverable is the crossfaded MP3 plus a `.vtt` and `.transcript.md` pair.

Host naming is handled purely at the prompt layer: `prompts/podcast-tutor.md` gains a `{hosts}` placeholder and an explicit HOST INTRODUCTION section. No code changes in the generation path itself.

### Pipeline (inside the background agent)

```
1. notebooklm artifact wait            # existing
2. notebooklm download audio           # existing → <out>/podcast-<theme>-YYYY-MM-DD.raw.mp3
3. python assemble_audio.py            # new → <out>/podcast-<theme>-YYYY-MM-DD.mp3
                                       #   (or cp raw→final if intro skipped/failed)
4. python transcribe_audio.py          # new, INPUT is raw audio, OUTPUT is offset by the
                                       #   ACTUAL final offset (0 if assembly fell back)
                                       #   → <out>/*.vtt + *.transcript.md
5. Report back with all file paths + per-stage warnings
```

**Why assemble first, but transcribe from raw audio:** Transcription needs two things: (a) clean speech-only audio to avoid pyannote being confused by the music bed, and (b) a correct timestamp offset for the final MP3. Running assembly first tells us the ACTUAL `final_offset_seconds` (0 if assembly was skipped or failed, `effective_intro_length - effective_crossfade` if it succeeded). We then feed the raw MP3 to Whisper/pyannote but offset the VTT timestamps by the actual final offset. This keeps diarization clean while guaranteeing VTT aligns with the delivered final audio.

**Retaining `.raw.mp3`:** The raw file stays on disk after assembly so post-processing can be re-run without re-generating. The existing `cleanup_days * 2` state-prune mechanism only prunes run records, not output files — so `.raw.mp3` files accumulate unless we actively manage them. See section 6 below for the explicit cleanup policy.

Steps 3 and 4 are skippable independently: no intro music configured → skip 3 (cp raw→final, `vtt_offset=0`); `transcript.enabled: false` or hard error → skip 4. The MP3 is the primary deliverable; transcript is best-effort. If step 3 fails but step 4 has been requested, step 4 proceeds with `vtt_offset=0` because the final is the raw.

### Config additions (`kb.yaml`)

```yaml
integrations:
  notebooklm:
    podcast:
      # existing: format, length, etc.

      # NEW
      intro_music: "~/path/to/intro.mp3"         # absolute or ~-expanded path; null/missing → skip crossfade
      intro_music_length_seconds: 12             # target clip length (10-15 reasonable); default 12
      intro_crossfade_seconds: 3                 # default 3

      hosts: ["瓜瓜龙", "海发菜"]                   # primary pair; defaults baked in
      extra_host_names: []                       # optional overflow pool for diarization with >2 clusters

      transcript:
        enabled: <set by kb-init>                # true if HF token + both licenses accepted, else false
        model: "large-v3"                        # faster-whisper model size
        device: "auto"                           # auto | cpu | cuda (mps not supported)
        language: "zh"                           # whisper language hint
```

All four blocks are optional — with no config, the skill runs with built-in defaults. Notes on defaults:

- `intro_music`: no default; intro is skipped when missing.
- `hosts`: default `["瓜瓜龙", "海发菜"]` built into the skill.
- `transcript.enabled`: kb-init writes an explicit value based on whether the HF token + pyannote licenses are in place at setup. If kb-init has never run (e.g., a project that predates this spec), `enabled` is absent and the skill treats it as `false` — better to silently skip transcripts than to emit per-episode HF errors. The user can set `enabled: true` manually after completing HF setup.
- All other `transcript.*` keys have reasonable built-in defaults.

### New files

- `plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py` — ffmpeg crossfade wrapper.
- `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py` — faster-whisper + pyannote diarization producing VTT + markdown.
- `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt` — new venv dependencies (`faster-whisper`, `pyannote.audio`, `PyYAML`).

### Modified files

- `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md` — brand fix, `{hosts}` placeholder, HOST INTRODUCTION section.
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — workflow reorder (render prompt in new step 6a' BEFORE hashing in 6b'); dedup algorithm with `postproc_hash` + `postproc_complete` predicate; `podcast_outputs` in run record; step 6i uses pre-rendered prompt; step 6k extended background agent (assemble, then transcribe raw audio using the actual offset); step 7 new sidecar fields; Cleanup workflow deletes `raw_audio` when pruning records; new `cleanup --raw-audio` option.
- `plugins/kb/skills/kb-publish/SKILL.md` — sidecar import (step 2b) and registry update (step 8b) extended to preserve `intro_applied`, `hosts`, and `transcript` fields through state transitions.
- `plugins/kb/skills/kb-init/SKILL.md` — adds `faster-whisper` / `pyannote.audio` to the notebooklm venv setup; ffmpeg check; HuggingFace token + both pyannote license prompts; persists `transcript.enabled` based on setup outcome.

## Detailed Design

### 1. Prompt changes — host naming and brand fix

File: `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md`

**Brand fix.** Line 3 currently reads:

> This is an episode of "My Lessons Learned" — a technical podcast where two hosts break down AI/ML concepts…

Rewrite to:

> This is an episode of 全栈AI — a technical podcast where two hosts break down AI/ML concepts…

**New `{hosts}` placeholder.** Add a new block directly under `{series_context}`:

```
{hosts}
```

When rendered by the skill at runtime, `{hosts}` is replaced with:

```
HOSTS:
This episode has two hosts: {host0} and {host1}.
They address each other and refer to themselves by these names throughout the episode.
{host0} typically drives explanations; {host1} asks the sharp follow-up questions. Either host may take either role — keep it natural, not rigid.
```

with `{host0}` / `{host1}` substituted from the resolved host pool (default `瓜瓜龙` / `海发菜`).

**New HOST INTRODUCTION section.** Inserted between `OPENING` and `EPISODE FLOW`:

```
HOST INTRODUCTION (first 10-15 seconds of dialogue):
Open with a warm, natural self-introduction. Example shape:
  {host0}: "Hi 大家好, 欢迎收听全栈AI, 我是{host0}."
  {host1}: "我是{host1}. 今天我们要聊的是..."
Keep it brief — one or two exchanges. Then flow directly into the hook described in OPENING.
Throughout the episode, the hosts address each other by name at natural moments ("{host1} 你刚才说...", "{host0} 那这个和 X 有什么关系?").
```

`{host0}` / `{host1}` are substituted the same way as in the `{hosts}` block — they are literal placeholder tokens in the prompt template, consistent with `{series_context}` and `{lesson_list}`.

### 2. SKILL.md changes — host pool resolution (step 6i)

After reading `prompts/podcast-tutor.md` in step 6i, the skill now performs these substitutions in order:

1. `{series_context}` — from episode registry, as today.
2. `{lesson_list}` — from the episode's lesson grouping, as today.
3. **`{hosts}` — NEW.** Build the host pool:
   - `hosts = kb.yaml → integrations.notebooklm.podcast.hosts`, defaulting to `["瓜瓜龙", "海发菜"]`.
   - `extra = kb.yaml → integrations.notebooklm.podcast.extra_host_names`, defaulting to `[]`.
   - `host_pool = hosts + extra`. Must contain at least 2 entries (validate; if not, error clearly).
   - Substitute `{host0}` with `host_pool[0]` and `{host1}` with `host_pool[1]` throughout the prompt (both in the new `{hosts}` block and the new HOST INTRODUCTION section).
4. Remaining text substitutions (lesson titles in the `{lesson_list}` block) as today.

The `extra_host_names` pool is not used in the prompt (NotebookLM produces 2 voices). It is consumed by the transcription step for diarization overflow (see section 4.3).

Persist the resolved `host_pool[:2]` in the sidecar manifest as `hosts: [<host0>, <host1>]` so downstream tools and future reruns can see which names were used.

### 3. Audio assembly — `assemble_audio.py`

**Inputs (CLI):**

```
--raw-audio PATH           # NotebookLM's downloaded MP3
--intro PATH               # intro music file (any ffmpeg-decodable format)
--output PATH              # final MP3 path
--intro-length SECONDS     # default 12
--crossfade SECONDS        # default 3
--json                     # emit JSON status to stdout
```

**Behavior:** Single `ffmpeg` invocation:

```
ffmpeg -y \
  -t {effective_intro_length} -i {intro} \
  -i {raw_audio} \
  -filter_complex "[0:a][1:a]acrossfade=d={effective_crossfade}:c1=tri:c2=tri[a]" \
  -map "[a]" -c:a libmp3lame -b:a 192k \
  {output}
```

- `-t {effective_intro_length}` trims the intro to exactly that many seconds. `acrossfade` overlaps the tail of input 1 with the head of input 2 for `{effective_crossfade}` seconds, producing total output duration `effective_intro_length + raw_audio_duration - effective_crossfade`.
- The listener hears `(effective_intro_length - effective_crossfade)` seconds of music-only, then `effective_crossfade` seconds of music fading into dialogue.
- `c1=tri c2=tri` uses triangular fade curves (smooth, no clicks).
- Output is MP3 @ 192 kbps (matches NotebookLM's quality).

**Preflight validation:** Probe the intro with `ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 {intro}` to get `intro_duration`. Compute:

```
effective_intro_length = min(requested_intro_length, intro_duration)
effective_crossfade    = min(requested_crossfade, effective_intro_length - 0.5)
```

`acrossfade` overlaps inside the intro length itself, so `intro_duration >= effective_intro_length` is the only hard requirement. The `effective_crossfade < effective_intro_length` constraint (`- 0.5` keeps at least 0.5s of music-only head) prevents degenerate cases. If `intro_duration < 1.5s`, skip assembly with a warning (too short to be a meaningful intro).

Emit warnings when values are clamped so the user knows the intro file is smaller than configured.

**Error handling:**

| Condition | Behavior |
|---|---|
| `intro_music` missing/null in kb.yaml | Skill skips calling `assemble_audio.py`; copies raw→final (`cp`, not `mv`, to retain `.raw.mp3`). |
| `intro_music` path doesn't exist | Warn, skip assembly, copy raw→final. Do NOT fail the episode. |
| Intro clip too short for configured crossfade | Clamp as above, or skip with warning. |
| ffmpeg nonzero exit | Keep the raw MP3 as final output, log ffmpeg stderr, set `intro_applied: false` in sidecar manifest. |

**Outputs:**

- `--output` file written on success.
- JSON to stdout (when `--json` set): `{"success": bool, "intro_applied": bool, "output": "<path>", "duration_seconds": <number>, "effective_intro_length": <number>, "effective_crossfade": <number>, "final_offset_seconds": <number>, "warnings": [<str>...], "error": "<str>" or null}`
- `final_offset_seconds` is `effective_intro_length - effective_crossfade` on success, `0` on failure. This is the single source of truth for the VTT offset: step 6k reads it directly from this JSON rather than recomputing, so any future script-side clamping changes flow through automatically.

### 4. Transcription — `transcribe_audio.py`

**Inputs (CLI):**

```
--audio PATH               # the RAW NotebookLM MP3 (pre-assembly, no music)
--hosts JSON               # JSON array of candidate host names, longest pool first
                           #   e.g. '["瓜瓜龙","海发菜","嘉宾C"]'
--output-vtt PATH
--output-md PATH
--vtt-offset-seconds FLOAT # add this offset to all VTT timestamps so captions
                           # align to the FINAL MP3 (which may start with music).
                           # Default 0 (no offset). The skill passes
                           # `actual_vtt_offset`, which equals
                           # `effective_intro_length - effective_crossfade`
                           # ONLY when assembly actually succeeded; if assembly
                           # was skipped or failed (the final is the raw),
                           # the skill passes 0. Never assume this value from
                           # config alone — derive it from assembly outcome.
--model NAME               # default from config: large-v3
--device {auto|cpu|cuda}   # default auto → cpu on macOS, cuda if available on Linux/NVIDIA
--language STR             # default zh
--title STR                # optional transcript H1 title (default derived from filename)
--json
```

Note: `mps` is intentionally omitted — faster-whisper does not support Metal / MPS (see SYSTRAN/faster-whisper issue #911). Apple Silicon runs on CPU; CTranslate2 CPU is highly optimized and a ~30-minute podcast transcribes in a few minutes. The `HF_HOME` env var is respected through the normal HuggingFace cache mechanism; no custom cache flag is needed.

**Model reuse (important — do NOT re-download):**

`~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3` already exists on the user's Mac (from the VoxToriApp repo's prior downloads). `faster-whisper` loads models from this exact cache path by convention — no action required, it will auto-detect. The script MUST NOT set a custom cache path that would bypass this existing cache. If a user wants to override, they can via `HF_HOME` or the explicit `--hf-cache-dir` flag.

Pyannote's `speaker-diarization-3.1` pipeline is **not** cached yet and will download on first run (~150MB). First-run setup in `kb-init` handles the HuggingFace token requirement — see section 7.

**Pipeline — three stages:**

#### 4.1 Transcription stage (faster-whisper)

```python
from faster_whisper import WhisperModel

model = WhisperModel(args.model, device=device_resolved, compute_type="auto")
segments, info = model.transcribe(
    args.audio,
    language=args.language,
    word_timestamps=True,
    vad_filter=True,
)
whisper_segments = [
    {"start": s.start, "end": s.end, "text": s.text.strip(),
     "words": [{"start": w.start, "end": w.end, "word": w.word} for w in s.words]}
    for s in segments
]
```

- `vad_filter=True` reduces hallucinations in silent regions. Since we transcribe the RAW audio (no music), the `vad_filter` is not load-bearing for music skipping — it's just a general quality improvement.
- `device="auto"` resolves to `cuda` if available on Linux/NVIDIA, otherwise `cpu`. On macOS (Apple Silicon or Intel), we always use `cpu` because faster-whisper / CTranslate2 does not support Metal/MPS. CPU performance with `compute_type="auto"` (typically `int8_float16` or `int8`) is adequate for episode-length audio.

#### 4.2 Diarization stage (pyannote.audio)

```python
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=os.environ.get("HUGGINGFACE_TOKEN"),
)
# NotebookLM always produces a two-host podcast. Since we're diarizing the raw
# (music-free) audio, pinning num_speakers=2 is safe and eliminates pathological
# 1-cluster / 3-cluster outcomes.
diarization = pipeline(args.audio, num_speakers=2)
diarization_turns = [
    {"start": turn.start, "end": turn.end, "speaker": label}
    for turn, _, label in diarization.itertracks(yield_label=True)
]
```

Pyannote labels speakers as `SPEAKER_00`, `SPEAKER_01`, etc. With `num_speakers=2`, there will always be exactly 2 distinct labels (or 1 if pyannote fails to detect a second speaker in a very short clip).

The `extra_host_names` pool is retained in config because it's low-cost future-proofing: if NotebookLM ever offers a debate format with 3+ voices, or if the user manually edits a transcript with a guest speaker, the pool is available. For this spec's scope, only the first 2 entries are used.

#### 4.3 Alignment + labeling

Whisper segments can span multiple diarization turns, especially during fast host exchanges. Naive "one speaker per whisper segment" labeling would mis-assign whole segments when a turn change happens mid-segment. The labeling logic uses word-level timestamps (which we already collected via `word_timestamps=True`) to split at diarization boundaries:

1. For each whisper segment, iterate its words with their `(start, end)` timestamps.
2. For each word, find the diarization turn that contains its midpoint `(start + end) / 2`. If no turn contains it, use the turn with the largest overlap or (if none) the most recent speaker.
3. Group consecutive words with the same speaker into sub-segments. Each sub-segment inherits its own `(start, end)` from its first and last words.
4. Treat each sub-segment as a VTT cue and as a transcript turn.

When a whisper segment is cleanly within a single diarization turn (the common case), this degenerates to the whole-segment rule. When it spans two turns, it is split into two sub-segments with correct speaker labels.

After sub-segmentation, map `speaker_id → host_name`:

1. Build the list of speaker labels in order of **first aligned speech segment** — i.e., for each distinct `speaker_id`, find the earliest whisper segment that aligned to it, sort by that timestamp. (Using the earliest aligned speech, not the earliest raw diarization turn, avoids being fooled by spurious pre-dialogue diarization activity.)
2. Map the first distinct `speaker_id` → `host_pool[0]` (瓜瓜龙 by default).
3. Map the second distinct `speaker_id` → `host_pool[1]` (海发菜 by default).
4. If a third or further speaker ever appears (possible if user swaps in a guest-format audio, not with default NotebookLM two-host output): use `host_pool[i]` if available, else synthesize `嘉宾A`, `嘉宾B`, …

**Self-intro validation (best-effort):** After labeling, inspect the first speech segment assigned to `host_pool[0]`. If its text contains `host_pool[1]`'s name but NOT `host_pool[0]`'s name, and the first segment for `host_pool[1]` contains `host_pool[0]`'s name but not its own, swap the mapping. This catches the rare case where the hosts disobey the prompt ordering. Log the swap as a warning so the user can confirm.

**Edge cases:**

- **Whisper segment has no overlapping diarization turn** (silence or edge of clip): assign to the most recently labeled speaker. If at the very start, assign to `host_pool[0]`.
- **Diarization returns only 1 cluster** (should not happen with `num_speakers=2` on two-speaker audio, but possible with malformed input): label everything as `host_pool[0]`, log warning.
- **Diarization returns >2 clusters** (pyannote ignores `num_speakers` hint in unusual cases): use `host_pool[i]` in first-appearance order, fall back to `嘉宾A/B/C` only if pool is exhausted.

#### 4.4 Output formats

**WebVTT** (`<output-vtt>`):

VTT timestamps are written as `segment.start + vtt_offset_seconds` and `segment.end + vtt_offset_seconds`, where `vtt_offset_seconds` is passed via CLI by the skill as `actual_vtt_offset`. That value is `effective_intro_length - effective_crossfade` ONLY when assembly actually succeeded (e.g., 9s for default 12s + 3s); if assembly was skipped or failed and the final is the raw audio, `actual_vtt_offset = 0`. This guarantees cues always align to the delivered final MP3 regardless of assembly outcome.

Example for a default 12s + 3s intro (offset = 9s), where raw dialogue starts at 0.240s:

```
WEBVTT

00:00:09.240 --> 00:00:13.120
<v 瓜瓜龙>大家好, 欢迎收听全栈AI, 我是瓜瓜龙.

00:00:13.120 --> 00:00:18.560
<v 海发菜>我是海发菜. 今天我们要聊的是 KV Cache.
```

One cue per aligned sub-segment (after splitting whisper segments at diarization boundaries — see section 4.3). Use `<v NAME>...` voice tag so WebVTT-aware players can style per-speaker.

When `--vtt-offset-seconds 0` (no intro, or user requests raw-aligned VTT), cues start near 0.

**Markdown** (`<output-md>`):

```markdown
# 全栈AI — KV Cache (2026-04-20)

**瓜瓜龙:** 大家好, 欢迎收听全栈AI, 我是瓜瓜龙.

**海发菜:** 我是海发菜. 今天我们要聊的是 KV Cache.
```

Consecutive segments from the same speaker are merged into one paragraph (joined by a space, trimming redundant whitespace).

**Title handling:** If `--title` is provided, use it verbatim (no prefixing). If `--title` is omitted, derive from the audio filename: `podcast-<theme>-YYYY-MM-DD.raw.mp3` → `全栈AI — <theme> (YYYY-MM-DD)`. The skill always passes an explicit `--title`, so the script-side derivation is just a fallback for standalone invocations.

**Error handling:**

| Condition | Behavior |
|---|---|
| `transcript.enabled: false` in config | Skill skips calling `transcribe_audio.py`; no error. |
| HuggingFace token missing | Script fails cleanly with exit code 3 and a clear message. Skill logs warning, sets `transcript.applied: false` in sidecar, episode still succeeds. |
| faster-whisper model download fails (offline) | Exit code 4. Skill logs, sets `transcript.applied: false`, episode still succeeds. |
| pyannote / whisper runtime exception | Exit code 5. Same treatment. |
| Diarization produces 1 cluster | Produce transcripts with single-speaker labels + warning; exit 0 (success). |

**Output:** JSON to stdout: `{"success": bool, "vtt": "<path>", "markdown": "<path>", "speaker_count": <int>, "duration_seconds": <float>, "warnings": [<str>...], "error": "<str>" or null}`.

### 5. SKILL.md changes — step 6k (extended background agent prompt)

The existing step 6k dispatches a background agent to `notebooklm artifact wait` and `notebooklm download audio`. Extended prompt (assemble-first so transcription sees the actual final offset):

Note: `<filename_stem>` below is the per-episode filename stem (without extension), e.g., `podcast-kv-cache-2026-04-20`. Derived using the same rules as the existing skill (section "Output filename logic" in SKILL.md).

**Shell safety:** Every path interpolated into a shell command must be quoted (prefer passing values through argv arrays to `subprocess.run` directly, or use `shlex.quote` when a shell string is unavoidable). Configured paths can contain spaces, Chinese characters, or other shell-special characters. All command templates in this spec are illustrative — the implementation must not inline unquoted user-controlled values.

The main conversation computes, BEFORE dispatching the agent:
- `effective_intro_length` and `effective_crossfade` via ffprobe (if intro music configured and the file exists), using the formula from section 3. These belong to `postproc_hash` ONLY — they do NOT go into `params_hash`. If the intro file is missing, too short, or not configured, set `intro_music_configured = false`, `effective_intro_length = 0`, `effective_crossfade = 0`, `desired_vtt_offset = 0`, and compute `postproc_hash` with those zero values (stable hash input).
- `desired_vtt_offset = effective_intro_length - effective_crossfade` (this is what we WANT; the ACTUAL offset depends on whether assembly succeeds).
- The title string: `全栈AI — <theme> (YYYY-MM-DD)` — no double-prefix since the script preserves explicit --title verbatim.

```
Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download,
assemble with intro music, then transcribe with the correct offset.

1. source <venv>/bin/activate && notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
   If exit != 0, report and stop.

2. source <venv>/bin/activate && notebooklm download audio <output_path>/<filename_stem>.raw.mp3 -n <notebook_id>
   If exit != 0, report and stop.

3. intro_applied = false       # will be set true if assembly succeeds
   actual_vtt_offset = 0
   If {intro_music_configured}:
      python3 <skill_dir>/scripts/assemble_audio.py \
        --raw-audio <output_path>/<filename_stem>.raw.mp3 \
        --intro <intro_music> \
        --output <output_path>/<filename_stem>.mp3 \
        --intro-length <effective_intro_length> \
        --crossfade <effective_crossfade> \
        --json
      Parse the JSON.
      If success AND intro_applied=true:
         intro_applied = true
         actual_vtt_offset = <final_offset_seconds from assembly JSON>   # single source of truth
      Else:
         cp <output_path>/<filename_stem>.raw.mp3 <output_path>/<filename_stem>.mp3
         intro_applied = false
         actual_vtt_offset = 0
   Else:
      cp <output_path>/<filename_stem>.raw.mp3 <output_path>/<filename_stem>.mp3
      intro_applied = false

4. If {transcript_enabled}:
      python3 <skill_dir>/scripts/transcribe_audio.py \
        --audio <output_path>/<filename_stem>.raw.mp3 \
        --hosts '<json-encoded host pool>' \
        --output-vtt <output_path>/<filename_stem>.vtt \
        --output-md <output_path>/<filename_stem>.transcript.md \
        --vtt-offset-seconds <actual_vtt_offset> \
        --model <model> \
        --device <device> \
        --language <language> \
        --title "全栈AI — <theme> (YYYY-MM-DD)" \
        --json
      Record transcript.applied, speaker_count, warnings.
      Transcription failure must NOT fail the episode.
   Else:
      transcript.applied = false

5. Report JSON with all file paths + per-stage status:
   {
     "raw_audio": "<output_path>/<filename_stem>.raw.mp3",
     "final_audio": "<output_path>/<filename_stem>.mp3",
     "intro_applied": bool,
     "vtt_offset_used": <seconds>,
     "transcript": {"vtt": "...", "markdown": "...", "applied": bool, "speaker_count": int},
     "warnings": [...]
   }
```

The agent does not write state — it only produces files and reports. The main conversation (step 7) updates state and writes the sidecar manifest using the reported values.

**Raw MP3 retention:** Use `cp` (not `mv`) in every no-intro / assembly-fallback branch so the raw file is retained alongside the final, enabling future re-assembly/re-transcription without re-generation. The raw file is deleted when its run record is pruned (see section 6) or via explicit `cleanup --raw-audio`.

### 6. Dedup, workflow ordering, and session recovery

The existing `params_hash` for the podcast workflow covers `format + length + language + instruction_template`, and the current SKILL.md computes it in step 6b — BEFORE prompt rendering in step 6i. That ordering is broken for this spec: the host pool, brand fix, and series bible all flow through the rendered prompt, so if hashing runs before rendering, none of those changes bust the hash.

**Required workflow reorder (in `kb-notebooklm/SKILL.md`):**

Move host resolution, series-bible compilation, and full prompt rendering from step 6i to a new step 6a' that runs before the dedup hash in step 6c. Concretely:

```
6a. Limit sources (existing)
6a'. (NEW) Resolve host pool, compile series bible, render podcast-tutor.md → rendered_prompt
6b. Compute sources_hash (existing)
6b'. (NEW) Compute params_hash using rendered_prompt, and postproc_hash using post-processing settings
6c. Dedup check against both hashes
6d. Empty-selection check
6e-6h. Create notebook, persist, add sources, wait (existing)
6i. Call notebooklm generate audio using the already-rendered prompt
6j-6k. Persist run record, spawn background agent
```

This ensures host/prompt/brand changes bust `params_hash` deterministically.

**New `params_hash` composition for podcast workflow:**

```
params_hash = sha256(
    format
  + length
  + language
  + sha256(rendered_prompt)           # captures {series_context}, {lesson_list}, {hosts},
                                      # brand text — any prompt change busts the hash
  + JSON(host_pool[:2])               # explicit, in case prompt templating ever changes
)
```

Intro music and transcript settings are NOT part of `params_hash`. Only prompt-affecting settings go here.

**Post-processing re-run without re-generation:**

A second hash, `postproc_hash`, captures only the post-processing parameters:

```
postproc_hash = sha256(
    intro_music_path
  + intro_music_mtime
  + intro_music_size                  # guards against same-path replacement w/ preserved mtime
  + intro_music_content_sha256        # authoritative: detects any content change
  + requested_intro_length            # user intent — changing config should refresh metadata
  + requested_crossfade_seconds       # even when clamping makes effective values equal
  + effective_intro_length            # derived — changes with file or clamp
  + effective_crossfade               # derived — changes with file or clamp
  + transcript.enabled
  + transcript.model
  + transcript.language
  + JSON(host_pool)                   # transcript uses full pool for labeling
)
```

**On content-hashing the intro file:** Intro music files are small (typically <1 MB for 10-15s clips) and hashed once per run, so reading + SHA-256 is negligible (<50ms). This is the authoritative change-detector — `mtime` + `size` are fallbacks for robustness. If a user replaces the file with identical content (unusual), no re-assembly happens, which is correct.

**On including requested values:** Including both `requested_*` and `effective_*` means changing `intro_crossfade_seconds` from 3 to 2 busts the hash even if the intro file is so short that both clamp to the same effective value. The user's config intent is respected, and the refreshed run surfaces any new clamp warnings. This is a deliberate choice over the alternative (semantic-output-only) — users editing config values expect to see the result reflected.

If the intro file path is null (intro not configured), all intro-related fields in the hash are set to empty strings for deterministic hashing.

**Completeness predicate.** Beyond hash matching, determine whether the stored run is actually fully processed:

```
postproc_complete(run) =
  final_audio exists AND
  (intro_music_configured ? run.podcast_outputs.intro_applied == true : true) AND
  (transcript_enabled ? (
      run.podcast_outputs.transcript_applied == true AND
      run.podcast_outputs.vtt exists AND
      run.podcast_outputs.transcript_md exists
  ) : true)
```

The `manifest` path in `podcast_outputs` is NOT part of the completeness check — it's transient (kb-publish deletes it after consumption) and its absence is a good state, not an incomplete one. The recovery logic must explicitly exclude `manifest` from existence checks.

Dedup extended algorithm (in step 6c of the workflow):

1. Match `workflow + sources_hash + params_hash`.
2. If match found with all artifacts `completed`:
   - If `postproc_hash` matches AND `postproc_complete(run)` is true: skip entirely.
   - If `postproc_hash` differs OR `postproc_complete(run)` is false:
     - If `raw_audio` exists on disk: re-run post-processing only (assembly + transcription from the retained raw).
     - If `raw_audio` missing: fall back to full regeneration, warn user.
3. If match found with any artifact `pending`: session recovery as today.
4. If match found with any artifact `failed`: partial retry as today.
5. No match: full generation.

**Why the `postproc_complete` predicate matters:** a run whose transcription failed with `transcript.enabled=true` has `transcript_applied=false` even though the hash matches. Without the predicate, the second run would also skip. With the predicate, the second run sees the work is incomplete and retries — consistent with "fixing HF/token issues and rerunning should recover" user expectation.

**Failures that persistently block the predicate** (e.g., user never fixes HF token) will not cause NotebookLM regeneration because the raw audio is retained and re-post-processing is cheap. The user simply sees "transcript still failing — check HF setup" until they resolve the underlying issue.

**Extended run record schema:** The current run record stores `artifacts[].output_files`. For post-processing recovery to work reliably, the podcast run record needs a structured `podcast_outputs` object with explicit paths:

```yaml
runs:
  - workflow: podcast
    sources_hash: sha256...
    params_hash: sha256...
    postproc_hash: sha256...          # NEW — post-processing parameters
    podcast_outputs:                  # NEW — structured post-processing outputs
      raw_audio: /abs/path/podcast-<stem>.raw.mp3
      final_audio: /abs/path/podcast-<stem>.mp3
      vtt: /abs/path/podcast-<stem>.vtt           # null if transcript disabled/failed
      transcript_md: /abs/path/podcast-<stem>.transcript.md
      manifest: /abs/path/podcast-<stem>.mp3.manifest.yaml
      intro_applied: true|false
      transcript_applied: true|false
    artifacts:
      - type: audio
        status: completed
        output_files: [<final_audio path>]  # kept for backwards compat
    notebook_id: ...
```

Post-processing recovery reads `podcast_outputs`, checks existence of each referenced file, and:
- If `raw_audio` exists and `postproc_hash` differs from current config: re-run post-processing only.
- If `raw_audio` missing but `final_audio` exists and matches current `postproc_hash`: treat as completed, no action.
- If `raw_audio` missing and `postproc_hash` differs: fall back to full regeneration.

`kb-publish` consumes only `<final_audio>.manifest.yaml` (the sidecar), which it deletes after import. The run record's `manifest` field points to that path but is understood to be transient — if the file is gone, that just means kb-publish has already consumed it (a good state, not an error).

**Forward migration:** Existing run records written before this change have no `postproc_hash` and no `podcast_outputs`. The dedup check treats missing `postproc_hash` as a mismatch (triggers post-processing re-run on the old output files if present, or full regeneration if not). Missing `podcast_outputs` is inferred from `artifacts[].output_files[0]` = final audio; raw audio is assumed absent (there was no retention mechanism before). No breaking change — old runs are either skipped (hash match, files present) or reprocessed fresh.

**`.raw.mp3` cleanup policy (explicit — the existing state prune does NOT delete files):**

The existing cleanup only prunes entries from `state.runs` older than `cleanup_days * 2`. It does NOT delete files. To prevent unbounded `.raw.mp3` accumulation:

1. When a run record is pruned from `state.runs`, the cleanup workflow now ALSO deletes the `raw_audio` file referenced in that record's `podcast_outputs` (if it still exists). The `final_audio`, `vtt`, `transcript_md`, and `manifest` are preserved — those are the user's deliverables.
2. An explicit `/kb-notebooklm cleanup --raw-audio` flag lets the user prune all retained raw files on demand without waiting for record pruning.
3. If the user wants to force re-post-processing on a run whose raw audio has been deleted, the skill falls back to full regeneration and warns: "Raw audio for this episode has been pruned — re-running from NotebookLM."

### 7. Sidecar manifest — extended fields

The existing sidecar schema (written in step 7) gains three top-level fields:

```yaml
# existing
audio: podcast-attention-2026-04-20.mp3
topic: "Flash Attention & KV Cache"
notebook_id: "uuid"
generated_date: 2026-04-20
depth: intermediate
concepts_covered: [...]
open_threads: [...]
source_lessons: [...]

# NEW
intro_applied: true                       # or false if skipped/failed
hosts: ["瓜瓜龙", "海发菜"]                  # hosts used in this episode's prompt (host_pool[:2])
transcript:
  vtt: podcast-attention-2026-04-20.vtt   # basename; alongside the audio
  markdown: podcast-attention-2026-04-20.transcript.md
  applied: true                           # false if disabled/failed
  speaker_count: 2                        # as detected by pyannote
```

**`kb-publish` preservation — requires an explicit update.** The current sidecar import in `kb-publish/SKILL.md` (Step 2b, around line 134) enumerates only the existing content manifest fields (`topic`, `depth`, `concepts_covered`, `open_threads`, `source_lessons`, `notebook_id`). The update path in Step 8b (around line 345) also only merges those fields. Without changes, the new sidecar fields would be dropped.

**Changes required in `kb-publish/SKILL.md`:**

1. Step 2b (sidecar import) — extend the "create new entry" and "merge fields" logic to also copy `intro_applied`, `hosts`, and the nested `transcript` object. Treat them as opaque pass-through fields; kb-publish doesn't interpret their values.
2. Step 8b (registry update) — when writing the registry entry, preserve `intro_applied`, `hosts`, `transcript` from the prior state if they were populated by sidecar import.
3. `episodes.yaml` schema documentation — add `intro_applied`, `hosts`, and `transcript` to the documented schema (they become optional fields on published entries).

The registry entries now look like:

```yaml
episodes:
  - id: 3
    title: "EP3 | Flash Attention 和 KV Cache..."
    # ... existing fields ...
    intro_applied: true
    hosts: ["瓜瓜龙", "海发菜"]
    transcript:
      vtt: podcast-attention-2026-04-20.vtt
      markdown: podcast-attention-2026-04-20.transcript.md
      applied: true
      speaker_count: 2
```

### 8. `kb-init` setup additions

`kb-init` is the one-time bootstrap skill. Changes:

**A. Install new venv dependencies** into the notebooklm venv (both fresh setup AND existing venvs — detect that this is an upgrade by checking for missing packages, and install them silently):

```
faster-whisper>=1.0.0
pyannote.audio>=3.1.0
PyYAML
```

(`PyYAML` is likely already in the venv via the existing notebooklm install; list it for safety.)

**B. Verify ffmpeg + ffprobe are on PATH.** If missing, tell the user:
```
brew install ffmpeg
```
and verify again. If still missing, disable intro-music by writing `intro_music: null` into the default config so the skill degrades gracefully instead of failing per-episode.

**C. Prompt for HuggingFace token and both pyannote model licenses.** Two models must be accepted because `speaker-diarization-3.1` depends on `segmentation-3.0`:

> Transcription uses `pyannote/speaker-diarization-3.1`, which internally uses `pyannote/segmentation-3.0`. Both require license acceptance on HuggingFace, plus a token.
>
> 1. Accept the license at https://huggingface.co/pyannote/segmentation-3.0
> 2. Accept the license at https://huggingface.co/pyannote/speaker-diarization-3.1
> 3. Create a token at https://huggingface.co/settings/tokens (read-scope is sufficient).
> 4. Add `export HUGGINGFACE_TOKEN=hf_...` to your shell profile.
> 5. Run `source ~/.zshrc` or restart your terminal.
>
> Skip this step if you don't plan to use transcripts.

Verify: `test -n "$HUGGINGFACE_TOKEN"`. The script can't easily verify license acceptance until first model download, so run a dry-run download check as the final setup step (gracefully failing if both licenses aren't accepted and pointing the user back to the license URLs).

**D. Persist the outcome in `kb.yaml`:**

```yaml
integrations:
  notebooklm:
    podcast:
      transcript:
        enabled: <true if HF token present and both licenses accepted, else false>
        model: "large-v3"
        device: "auto"
        language: "zh"
      # intro_music omitted if ffmpeg unavailable; left as commented-out placeholder otherwise
      hosts: ["瓜瓜龙", "海发菜"]
      extra_host_names: []
      intro_music_length_seconds: 12
      intro_crossfade_seconds: 3
```

**Rationale for `transcript.enabled` at setup time:** Setting `enabled: true` when the token/licenses are missing would produce per-episode error logs. Let setup gate this once, and let the user flip it to `true` later when they complete the HF setup.

**Note on cache reuse:** `faster-whisper` large-v3 is already cached on this machine from VoxToriApp's downloads at `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3`. `faster-whisper` auto-detects this via the standard HF cache path — no action needed. Do NOT override `HF_HOME` in this skill; let the cache be shared with any other whisper-using tools.

### 9. Workflow summary — what changes in the skill's steps

| Step | Current behavior | New behavior |
|---|---|---|
| 6a' (new) | — | Render prompt (host pool + series bible + lesson list) into `rendered_prompt` BEFORE hashing |
| 6b' Hash compute | `params_hash` over format/length/language/instruction | `params_hash` over sha256(rendered_prompt) + host pool; new `postproc_hash` for intro + transcript settings |
| 6c Dedup check | Matches on `workflow + sources_hash + params_hash` | Additionally inspects `postproc_hash` and `podcast_outputs`; if only post-processing settings changed and raw audio retained, re-run post-processing only |
| 6i Generate audio | Reads + renders prompt inline | Uses the already-rendered prompt from 6a' |
| 6k Background agent | Wait + download MP3 | Wait + download (`.raw.mp3`) + assemble (`.mp3`) + transcribe raw audio using the actual VTT offset from assembly outcome (`.vtt`, `.transcript.md`) |
| 7 On agent success | Write sidecar with content manifest fields | Also write `intro_applied`, `hosts`, `transcript.*` fields; store `postproc_hash` + structured `podcast_outputs` in run record |
| Cleanup workflow | Prunes `runs` entries | Also deletes the `raw_audio` file referenced in pruned entries; new `--raw-audio` subflag |

## Testing & Verification

The project has no automated test suite at the repo level, but the two new Python scripts are substantial enough to warrant colocated unit tests. Add a `tests/` directory under `plugins/kb/skills/kb-notebooklm/scripts/` with:

**Unit tests (pytest, no network, no models required):**

1. `test_assemble_audio.py`:
   - Preflight math: requested 12s+3s on 12s file → effective 12s+3s (no clamp).
   - Preflight math: requested 12s+3s on 5s file → effective 5s + min(3, 4.5)=3s crossfade.
   - Preflight math: requested 12s+3s on 1s file → skip entirely.
   - Preflight math: requested 3s+2s on 3s file → effective 3s + 2s (exact).
   - ffmpeg command-building: verifies the constructed argv matches expected template.
   - JSON output shape on success and each failure mode.
2. `test_transcribe_audio.py`:
   - Timestamp offset formatting: 0.24s + 9s offset → `00:00:09.240`; 65.5s + 9s → `00:01:14.500`; 3600.1s + 9s → `01:00:09.100`.
   - VTT escaping: text containing `<`, `>`, `&` is properly escaped in cue body.
   - VTT voice tag escaping for host names that contain special characters.
   - Markdown paragraph merging: consecutive same-speaker segments are merged with a space; paragraph breaks inserted on speaker change.
   - Diarization label mapping: given synthetic whisper segments + synthetic diarization turns, verify first-appearance ordering picks `host_pool[0]` for the earliest speaker.
   - Whisper-segment splitting: given a single whisper segment whose words span two diarization turns, verify the output contains two sub-segments with the correct speaker assignments at the diarization boundary.
   - VTT offset sanity: invoking with `--vtt-offset-seconds 0` produces cues starting near 0; invoking with offset 9.0 produces cues starting near 9.0.
   - Self-intro swap: given a scenario where `host_pool[0]`'s first line mentions `host_pool[1]` but not itself, verify swap triggers and logs a warning.
   - Title derivation when `--title` omitted: `podcast-kv-cache-2026-04-20.raw.mp3` → `全栈AI — kv-cache (2026-04-20)`.
   - JSON output shape on success, missing HF token, model-download failure.
3. `test_params_hash.py` (if the hashing logic is implemented in a shared Python helper):
   - Verify hash changes when host pool changes.
   - Verify hash changes when prompt text changes.
   - Verify `postproc_hash` changes when intro config changes, but `params_hash` does not.

**Procedural end-to-end verification (by the human):**

1. **Prompt-only smoke test** — set `intro_music: null` and `transcript.enabled: false`, run `/kb-notebooklm podcast`. Listen to output: hosts introduce themselves as 瓜瓜龙 and 海发菜, brand is 全栈AI, no music intro, no transcript files.
2. **Assembly boundary** — run full workflow with real intro music. Use `ffprobe` on the final MP3 to verify duration ≈ `effective_intro_length + raw_duration - effective_crossfade`. Listen to the crossfade region.
3. **Transcription alignment** — open `.vtt` in VLC against the final MP3. First dialogue cue should appear around the `effective_intro_length - effective_crossfade` mark.
4. **Transcription degradation** — unset `HUGGINGFACE_TOKEN`, re-run. Verify script exits cleanly and skill produces a working MP3 with `transcript.applied: false` in the sidecar.
5. **Re-post-process without regeneration** — run once successfully, change `intro_music_length_seconds` in kb.yaml, re-run. Verify NotebookLM is NOT called again (check notebook creation log), but `postproc_hash` mismatch triggers re-assembly using the retained `.raw.mp3`.
6. **End-to-end publish** — full podcast run with all three features enabled, then run `/kb-publish` on the output. Inspect `episodes.yaml` and verify `intro_applied`, `hosts`, `transcript.*` fields are preserved in the published entry.
7. **Graceful degradation** — remove `intro_music` from kb.yaml, re-run full workflow. Verify MP3 is produced without music intro (raw promoted to final) and no errors.
8. **Backwards compatibility** — run the workflow on a pre-existing project without the new config keys. Verify it falls back to all defaults: default hosts, no intro music, transcript auto-disabled if HF token not present at setup time.
9. **Rerun after brand fix** — on a project with pre-change runs in state, verify re-running the workflow detects the `params_hash` change (new prompt) and regenerates rather than skipping.
10. **Assembly-failure VTT correctness** — configure an intro but point it at a broken file so `assemble_audio.py` fails. Verify: raw is promoted to final (`cp`), `intro_applied: false`, and the VTT cues start near 00:00:00 (offset=0), NOT at 9s.
11. **Rerun after transcription fix** — configure transcription but run once with `HUGGINGFACE_TOKEN` unset (transcript_applied=false). Set the token and re-run. Verify `postproc_complete` predicate detects the incomplete state and re-runs transcription only (no NotebookLM regeneration), using the retained raw audio.

## Open Questions

None — all design questions resolved in the brainstorm.

## References

- Existing skill: `plugins/kb/skills/kb-notebooklm/SKILL.md`
- Existing prompt: `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md`
- Downstream consumer: `plugins/kb/skills/kb-publish/SKILL.md`
- Whisper model cache (pre-existing): `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3`
- Related project using same models: `~/PycharmProjects/VoxToriApp/VoxToriApp` (WhisperKit CoreML variant; not reused by this skill since we need Python bindings, but the HF cache is shared via faster-whisper's Systran variant)
