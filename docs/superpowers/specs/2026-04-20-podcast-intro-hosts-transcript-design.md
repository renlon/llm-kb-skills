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
4. python transcribe_audio.py          # new → <out>/*.vtt + *.transcript.md
5. Report back with all file paths + per-stage warnings
```

Steps 3 and 4 are skippable independently: no intro music configured → skip 3 (just rename raw→final); `transcript.enabled: false` or hard error → skip 4. The MP3 is the primary deliverable; transcript is best-effort.

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
        enabled: true                            # default true
        model: "large-v3"                        # faster-whisper model size
        device: "auto"                           # auto | cpu | mps | cuda
        language: "zh"                           # whisper language hint
```

All four blocks are optional — with no config, the skill runs with built-in defaults (no intro music, default hosts, transcript enabled).

### New files

- `plugins/kb/skills/kb-notebooklm/scripts/assemble_audio.py` — ffmpeg crossfade wrapper.
- `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py` — faster-whisper + pyannote diarization producing VTT + markdown.
- `plugins/kb/skills/kb-notebooklm/scripts/requirements.txt` — new venv dependencies (`faster-whisper`, `pyannote.audio`, `PyYAML`).

### Modified files

- `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md` — brand fix, `{hosts}` placeholder, HOST INTRODUCTION section.
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — updated podcast workflow (step 6i for prompt injection, step 6k for extended background agent script, step 7 for new sidecar fields).
- `plugins/kb/skills/kb-init/SKILL.md` — adds `faster-whisper` / `pyannote.audio` to the notebooklm venv setup, prompts user for HuggingFace token.

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
  -t {intro_length} -i {intro} \
  -i {raw_audio} \
  -filter_complex "[0:a][1:a]acrossfade=d={crossfade}:c1=tri:c2=tri[a]" \
  -map "[a]" -c:a libmp3lame -b:a 192k \
  {output}
```

- `-t {intro_length}` trims the intro to exactly `intro_length` seconds. The crossfade overlaps the last `crossfade` seconds of that clip with the first `crossfade` seconds of the podcast, so the listener hears ~`(intro_length - crossfade)` seconds of music-only, then `crossfade` seconds of music fading into dialogue.
- `c1=tri c2=tri` uses triangular fade curves (smooth, no clicks).
- Output is MP3 @ 192 kbps (matches NotebookLM's quality).

**Preflight validation:** Probe the intro file with `ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 {intro}` to get its duration. If `duration < intro_length + crossfade` — for example an 8s file when config asks for 12s+3s — clamp `intro_length = duration - crossfade` and warn. If `duration < crossfade + 1`, skip assembly entirely with a warning.

**Error handling:**

| Condition | Behavior |
|---|---|
| `intro_music` missing/null in kb.yaml | Skill skips calling `assemble_audio.py`; renames raw→final. |
| `intro_music` path doesn't exist | Warn, skip assembly, rename raw→final. Do NOT fail the episode. |
| Intro clip too short for configured crossfade | Clamp as above, or skip with warning. |
| ffmpeg nonzero exit | Keep the raw MP3 as final output, log ffmpeg stderr, set `intro_applied: false` in sidecar manifest. |

**Outputs:**

- `--output` file written on success.
- JSON to stdout (when `--json` set): `{"success": bool, "intro_applied": bool, "output": "<path>", "duration_seconds": <number>, "warnings": [<str>...], "error": "<str>" or null}`

### 4. Transcription — `transcribe_audio.py`

**Inputs (CLI):**

```
--audio PATH               # the FINAL assembled MP3 (with intro)
--hosts JSON               # JSON array of candidate host names, longest pool first
                           #   e.g. '["瓜瓜龙","海发菜","嘉宾C"]'
--output-vtt PATH
--output-md PATH
--model NAME               # default from config: large-v3
--device {auto|cpu|mps|cuda}   # default auto
--language STR             # default zh
--hf-cache-dir PATH        # optional override; default HF_HOME / ~/.cache/huggingface
--title STR                # optional transcript H1 title
--json
```

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

- `vad_filter=True` skips the music-only portion cleanly so the transcript starts when dialogue starts (not "music playing" or hallucinated text).
- `device="auto"` resolves to `mps` on Apple Silicon, `cuda` if available, otherwise `cpu`.

#### 4.2 Diarization stage (pyannote.audio)

```python
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=os.environ.get("HUGGINGFACE_TOKEN"),
)
# Pin the search range. Do NOT pin num_speakers=2 exactly — music bed can fool the model.
diarization = pipeline(
    args.audio,
    min_speakers=2,
    max_speakers=max(2, len(host_pool)),
)
diarization_turns = [
    {"start": turn.start, "end": turn.end, "speaker": label}
    for turn, _, label in diarization.itertracks(yield_label=True)
]
```

Pyannote labels speakers as `SPEAKER_00`, `SPEAKER_01`, etc.

#### 4.3 Alignment + labeling

For each whisper segment, find the diarization turn with the largest time-overlap and assign its `speaker_id`. Then map `speaker_id → host_name`:

- Sort distinct `speaker_id`s by their first-appearance timestamp.
- Map `speaker_id[0]` → `host_pool[0]` (瓜瓜龙 by default).
- Map `speaker_id[1]` → `host_pool[1]` (海发菜 by default).
- Map `speaker_id[i]` → `host_pool[i]` if the pool has enough entries.
- If the pool is exhausted, synthesize fallback labels: `嘉宾A`, `嘉宾B`, `嘉宾C`, …

Rationale for ordering by first appearance: the prompt (section 1) instructs `host_pool[0]` to speak first in the self-introduction, so this mapping is reliable. If it ever inverts for a given episode, users can swap `hosts` order in `kb.yaml` or edit the plain-text transcript.

**Edge cases:**

- **Whisper segment has no overlapping diarization turn** (silence or edge of clip): assign to the most recently labeled speaker. If at the very start, assign to `host_pool[0]`.
- **Diarization produces only 1 cluster** (music fooled it, or very short episode): label everything as `host_pool[0]`, log warning.
- **Diarization produces >len(pool) clusters**: use pool first, then synthesize `嘉宾A/B/C`.

#### 4.4 Output formats

**WebVTT** (`<output-vtt>`):

```
WEBVTT

00:00:00.240 --> 00:00:04.120
<v 瓜瓜龙>大家好, 欢迎收听全栈AI, 我是瓜瓜龙.

00:00:04.120 --> 00:00:09.560
<v 海发菜>我是海发菜. 今天我们要聊的是 KV Cache.
```

One cue per whisper segment. Use `<v NAME>...` voice tag so WebVTT-aware players can style per-speaker.

**Markdown** (`<output-md>`):

```markdown
# 全栈AI — KV Cache (2026-04-20)

**瓜瓜龙:** 大家好, 欢迎收听全栈AI, 我是瓜瓜龙.

**海发菜:** 我是海发菜. 今天我们要聊的是 KV Cache.
```

Consecutive segments from the same speaker are merged into one paragraph (joined by a space, trimming redundant whitespace). The H1 title is taken from `--title` or derived from the audio filename (`podcast-<theme>-YYYY-MM-DD.mp3` → `全栈AI — <theme> (YYYY-MM-DD)`). Always prefixes the title with `全栈AI — ` per brand.

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

The existing step 6k dispatches a background agent with a prompt telling it to `notebooklm artifact wait` then `notebooklm download audio`. Extended prompt:

Note: `<filename_stem>` below is the per-episode filename stem (without extension), e.g., `podcast-kv-cache-2026-04-20`. Derived using the same rules as the existing skill (section "Output filename logic" in SKILL.md).

```
Wait for artifact <artifact_id> in notebook <notebook_id> to complete, then download,
assemble with intro music, and transcribe.

1. source <venv>/bin/activate && notebooklm artifact wait <artifact_id> -n <notebook_id> --timeout 2700
   If exit != 0, report and stop.

2. source <venv>/bin/activate && notebooklm download audio <output_path>/<filename_stem>.raw.mp3 -n <notebook_id>
   If exit != 0, report and stop.

3. If {intro_music_configured}:
      python3 <skill_dir>/scripts/assemble_audio.py \
        --raw-audio <output_path>/<filename_stem>.raw.mp3 \
        --intro <intro_music> \
        --output <output_path>/<filename_stem>.mp3 \
        --intro-length <intro_music_length_seconds> \
        --crossfade <intro_crossfade_seconds> \
        --json
      Record intro_applied and any warnings from the JSON.
      If assembly fails, mv <filename_stem>.raw.mp3 <filename_stem>.mp3 (fallback) and record intro_applied=false.
   Else:
      mv <output_path>/<filename_stem>.raw.mp3 <output_path>/<filename_stem>.mp3
      intro_applied = false (not configured).

4. If {transcript_enabled}:
      python3 <skill_dir>/scripts/transcribe_audio.py \
        --audio <output_path>/<filename_stem>.mp3 \
        --hosts '<json-encoded host pool>' \
        --output-vtt <output_path>/<filename_stem>.vtt \
        --output-md <output_path>/<filename_stem>.transcript.md \
        --model <model> \
        --device <device> \
        --language <language> \
        --title "全栈AI — <theme> (YYYY-MM-DD)" \
        --json
      Record transcript.applied, speaker_count, and warnings from the JSON.
      Transcription failure must NOT fail the episode — the MP3 is the primary deliverable.
   Else:
      transcript.applied = false (disabled).

5. Report JSON with all produced file paths + per-stage status:
   {
     "raw_audio": "...",
     "final_audio": "...",
     "intro_applied": bool,
     "transcript": {"vtt": "...", "markdown": "...", "applied": bool, "speaker_count": int},
     "warnings": [...]
   }
```

The agent does not write state — it only produces files and reports. The main conversation (step 7) updates state and writes the sidecar manifest using the reported values.

### 6. Sidecar manifest — extended fields

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

`kb-publish` does not need to act on these today — it just preserves them when merging the sidecar into `episodes.yaml`. Useful for debugging, future republishing flows, and eventually uploading transcripts to 小宇宙 if that ever becomes possible.

### 7. `kb-init` setup additions

`kb-init` is the one-time bootstrap skill. Extend the notebooklm venv setup step to install:

```
faster-whisper>=1.0.0
pyannote.audio>=3.1.0
PyYAML
```

(`PyYAML` is likely already in the venv via the existing notebooklm install.)

Also prompt the user once:

> Transcription uses `pyannote/speaker-diarization-3.1`, which requires accepting the model license at https://huggingface.co/pyannote/speaker-diarization-3.1 and a HuggingFace token.
> 1. Accept the model license at the URL above.
> 2. Create a token at https://huggingface.co/settings/tokens
> 3. Add `export HUGGINGFACE_TOKEN=hf_...` to your shell profile.
> 4. Run `source ~/.zshrc` or restart your terminal.
>
> Skip this step if you don't plan to use transcripts. (You can set `integrations.notebooklm.podcast.transcript.enabled: false` in kb.yaml.)

Record whether HF token is set. Write `transcript.enabled: <result>` into the default `kb.yaml` section so the user's setup decision is persisted.

**Note on cache reuse:** `faster-whisper` large-v3 is already cached on this machine from VoxToriApp's downloads at `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3`. `faster-whisper` auto-detects this via the standard HF cache path — no action needed. Do NOT override `HF_HOME` in this skill; let the cache be shared.

### 8. Workflow summary — what changes in the skill's steps

| Step | Current behavior | New behavior |
|---|---|---|
| 6i Generate audio | Reads prompt, substitutes `{series_context}` + `{lesson_list}` | Also substitutes `{hosts}`, `{host0}`, `{host1}` |
| 6k Background agent | Wait + download MP3 | Wait + download (`.raw.mp3`) + assemble (`.mp3`) + transcribe (`.vtt`, `.transcript.md`) |
| 7 On agent success | Write sidecar with content manifest fields | Also write `intro_applied`, `hosts`, `transcript.*` fields |

## Testing & Verification

The project has no automated test suite. Verification is procedural:

1. **Prompt-only smoke test** — set `intro_music: null` and `transcript.enabled: false`, run `/kb-notebooklm podcast`. Listen to output: hosts introduce themselves as 瓜瓜龙 and 海发菜, brand is 全栈AI, no music intro, no transcript files.
2. **Assembly test** — run `assemble_audio.py` standalone on an existing raw MP3 + test intro clip. Verify duration is approximately `intro_length + podcast_length - crossfade`, listen to the crossfade boundary.
3. **Assembly edge case** — run `assemble_audio.py` with a 5s intro when config asks for 12s + 3s. Verify it clamps, warns, and still produces a valid output.
4. **Transcription test** — run `transcribe_audio.py` on an assembled MP3 with `--hosts '["瓜瓜龙","海发菜"]'`. Verify the first two turns are labeled 瓜瓜龙 and 海发菜 in the order they appear. Open the `.vtt` in VLC against the MP3 and verify alignment.
5. **Transcription degradation** — unset `HUGGINGFACE_TOKEN`, re-run. Verify script exits cleanly with an error code and the skill produces a working episode MP3 with `transcript.applied: false` in the sidecar.
6. **End-to-end** — full podcast run with all three features enabled. Inspect final MP3, `.vtt`, `.transcript.md`, and sidecar manifest. Run `/kb-publish` on the output and verify sidecar fields are preserved in `episodes.yaml`.
7. **Graceful degradation** — remove `intro_music` from kb.yaml, re-run full workflow. Verify MP3 is produced without music intro and no errors.
8. **Backwards compatibility** — run the workflow on a project without the new config keys present. Verify it falls back to all defaults (default hosts, no intro music, transcript enabled if HF token present).

## Open Questions

None — all design questions resolved in the brainstorm.

## References

- Existing skill: `plugins/kb/skills/kb-notebooklm/SKILL.md`
- Existing prompt: `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md`
- Downstream consumer: `plugins/kb/skills/kb-publish/SKILL.md`
- Whisper model cache (pre-existing): `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3`
- Related project using same models: `~/PycharmProjects/VoxToriApp/VoxToriApp` (WhisperKit CoreML variant; not reused by this skill since we need Python bindings, but the HF cache is shared via faster-whisper's Systran variant)
