# Multi-Show Podcast Support Design

**Status:** Design in progress (2026-04-23)
**Skills:** all four podcast-adjacent skills (`kb`, `kb-init`, `kb-notebooklm`, `kb-publish`)
**Related:** Built on the episode-index feature (spec 2026-04-21). First of a three-spec series; next two build on this foundation (episode back-references on wiki articles; wiki as NotebookLM source).

## Problem

Everything that is currently hardcoded to "the podcast 全栈AI" must become a first-class concept: `show`. The code assumes one show today:

- `integrations.notebooklm.podcast.*` holds hosts, intro music, transcript language — all show-specific.
- `integrations.xiaoyuzhou.podcast_id` identifies one 小宇宙 podcast.
- `episodes.yaml` is implicitly "全栈AI's registry."
- `wiki/episodes/ep-N-*.md` — all for 全栈AI.
- Stub `created_by: ep-3` means "EP3 of 全栈AI" without saying so.
- Prompts say "EP3: Flash Attention" with no show qualifier.

User wants to scale beyond a single podcast eventually. The cheap fix now is to add `show` as a dimension everywhere; the data model supports N shows from day one, but we only populate 1 entry for now. Future shows are additive config.

## Goals

- Introduce `integrations.shows[]` in `kb.yaml` as the authoritative source of show identity.
- Scope all show-specific data (registry, wiki episode articles, stub back-refs, prompts) by show.
- Support `--show <id>` on all show-scoped commands with a silent default when only one show exists.
- Provide a one-shot `/kb migrate` command to convert the existing KB.
- Keep behavior for the single-show 全栈AI user identical (zero friction during and after migration).

## Non-goals (YAGNI)

- Cross-show episode indexing (e.g., "what's been covered in any show this month"). Each show owns its own index.
- Multi-language UI for commands (config can be per-show but CLI stays English).
- Cross-show concept canonicalization. `wiki/attention/flash-attention.md` is a vault-wide article that any show may reference; we do not attempt to partition `wiki/` itself by show.
- Episode back-references on non-episode wiki articles. That is the next spec (wiki-episode-backrefs); this spec only scopes enough for that next spec to work.
- `wiki/` folder partitioning by show. The concept catalog remains single, shared.
- Renaming the default registry file (`episodes.yaml` stays as-is; second show gets its own).

## Design Overview

Multi-show is a **data-model change, not a behavior change**. Every workflow (podcast generation, publish, backfill, dedup) still does exactly what it does today. The change is that every "which podcast" lookup flows through an explicit `show_id`, which defaults silently when there's only one show.

Three architectural moves:

1. **`kb.yaml` gains `integrations.shows[]`.** Each entry is self-contained per-show config. The existing `integrations.notebooklm.podcast.*` and `integrations.xiaoyuzhou.podcast_id` shrink as show-specific fields move out.
2. **Show-scoped paths.** `wiki/episodes/<show-id>/ep-<N>-<slug>.md` (nested). `episodes.yaml` stays at root for the default show; second show gets `episodes-<show-id>.yaml`. Each show's `episodes_registry` path is configured per-show.
3. **Show-aware references.** Episode references become `{show, ep}` pairs in YAML/JSON contexts. Prompt text uses the show's human `title` plus EP number. Wikilinks use the new nested path.

A new shared module `shows.py` provides the `Show` dataclass, `EpRef` value object, and resolution helpers used by every skill.

A new migration command `/kb migrate` converts existing single-show artifacts in-place, atomically.

## Detailed Design

### 1. `kb.yaml` schema after migration

```yaml
# Global infrastructure — shared by all shows
integrations:
  notebooklm:
    enabled: true
    cli_path: /absolute/path/to/notebooklm
    venv_path: /absolute/path/to/venv
    lessons_path: /absolute/path/to/lessons
    wiki_path: /absolute/path/to/wiki
    output_path: /absolute/path/to/output
    cleanup_days: 7
    max_sources_per_notebook: 45
    # NOTE: no `language` at this level anymore. Each show has its own.

  xiaoyuzhou:
    enabled: true
    browser_data: ".xiaoyuzhou-browser-data"
    staging_dir: "output/xiaoyuzhou-staging"
    venv_path: /absolute/path/to/venv
    # NOTE: no `podcast_id` here anymore. Each show has its own under `xiaoyuzhou.podcast_id`.
    # episodes_registry also moves to per-show.

  gemini:
    enabled: true
    model: gemini-2.5-flash-image
    cover_aspect: "1:1"

  # NEW: per-show entries
  shows:
    - id: quanzhan-ai
      title: 全栈AI
      description: "AI/ML 工程向的中文播客"
      default: true
      language: zh_Hans
      hosts: ["瓜瓜龙", "海发菜"]
      extra_host_names: []
      intro_music: /Users/dragon/Documents/MLL/assets/intro.mp3
      intro_music_length_seconds: 12
      intro_crossfade_seconds: 3
      podcast_format: deep-dive
      podcast_length: long
      transcript:
        enabled: true
        model: large-v3
        device: auto
        language: zh
      episodes_registry: episodes.yaml
      wiki_episodes_dir: wiki/episodes/quanzhan-ai
      xiaoyuzhou:
        podcast_id: "69ddba132ea7a36bbf1efa77"
```

### 2. Validation rules on config load

- `integrations.shows` MUST exist and be a non-empty list.
- Every `id` matches `^[a-z][a-z0-9\-]{1,31}$` (URL-safe slug, 2-32 chars).
- `id` values are unique across all shows.
- Exactly one show has `default: true` when there are 2+ shows. When there is only one show, `default` is optional; it is auto-treated as the default.
- `episodes_registry` paths are unique across shows.
- `wiki_episodes_dir` paths are unique across shows.
- `xiaoyuzhou.podcast_id` (optional per show) is unique when present.
- `episodes_registry` is a relative path; resolved against the project root (directory containing `kb.yaml`).
- `wiki_episodes_dir` is relative; resolved against the project root. Must be a subdirectory of `integrations.notebooklm.wiki_path`.
- Validation errors list every violation at once (not one-at-a-time).

### 3. Resolution semantics

`resolve_show(shows, show_id_arg)`:

- If `show_id_arg` is not None: return the show with that id, or raise `ShowNotFoundError`.
- Else if `len(shows) == 1`: return `shows[0]`.
- Else: return the show with `default: true`, or raise `AmbiguousShowError` if none.

`default_show(shows)` — same as `resolve_show(shows, None)`.

### 4. Reference format (`EpRef`)

Every episode reference becomes a `{show, ep}` pair.

Python:
```python
@dataclass(frozen=True)
class EpRef:
    show: str
    ep: int

    def to_dict(self) -> dict:
        return {"show": self.show, "ep": self.ep}

    def wikilink_stem(self, slug: str) -> str:
        """Return the path-without-.md used inside [[ ]] wikilinks."""
        return f"wiki/episodes/{self.show}/ep-{self.ep}-{slug}"

    @classmethod
    def from_any(cls, value, *, default_show: str | None = None) -> "EpRef":
        """Parse a legacy str (like 'ep-3') or a dict, raising on invalid.

        The `default_show` kwarg is only used when parsing legacy strings;
        any dict form must have explicit `show` and `ep` fields.
        """
```

YAML / JSON serialization: always the dict form `{show, ep}`. No legacy strings are accepted by post-migration code (legacy parsing is only in the migrator).

Filesystem: episode article lives at `<wiki>/episodes/<show>/ep-<N>-<slug>.md`. Obsidian wikilinks use the same path (without `.md`): `[[wiki/episodes/<show>/ep-<N>-<slug>]]`.

Prompt text: the series-bible rendering in podcast-tutor.md's `{series_context}` uses human-readable form: `"EP1 (全栈AI): GPU Computing & CUDA (intro)"` — show title parenthesized after EP number. Single-show KBs can omit the show suffix when all episodes in context are from the same show as the current one (implementation detail: render the full form only when prior episodes include any from a different show; otherwise keep the current terse form).

### 5. Touchpoints: what changes where

| Place | Before | After |
|---|---|---|
| `kb.yaml` | `notebooklm.podcast.hosts`, `notebooklm.podcast.intro_music`, ..., `xiaoyuzhou.podcast_id`, `xiaoyuzhou.episodes_registry` | Listed once under `integrations.shows[0].*` |
| `wiki/episodes/ep-N-<slug>.md` | flat | `wiki/episodes/<show-id>/ep-N-<slug>.md` |
| Stub `created_by: ep-1` | str | `{show: <id>, ep: 1}` |
| Stub `last_seen_by`, `best_depth_episode` | str | `{show: <id>, ep: N}` |
| Stub `referenced_by: [ep-1, ep-2]` | list of str | list of `{show, ep}` dicts |
| Episode article `index.concepts[].prior_episode_ref` | int | `{show, ep}` dict |
| Episode article body wikilinks | `[[wiki/episodes/ep-1-<slug>]]` | `[[wiki/episodes/<show>/ep-1-<slug>]]` |
| Series-bible prompt | `"EP1: GPU Computing & CUDA"` | `"EP1: GPU Computing & CUDA"` (single-show) OR `"EP1 (Show Title): ..."` (cross-show) |
| Dedup-judge prompt `prior_hits[].ep_id` | int | `{show, ep}` dict |
| `backfill-index --episode N` | `--episode 1` | `--show <id> --episode 1` (show optional when one show) |

### 6. New shared module: `plugins/kb/skills/kb-publish/scripts/shows.py`

Lives under kb-publish (it's the skill that most often needs show resolution) but is imported by kb-notebooklm too via the existing `sys.path.insert` pattern.

Public API:

```python
@dataclass(frozen=True)
class Show:
    id: str
    title: str
    description: str
    default: bool
    language: str
    hosts: list[str]
    extra_host_names: list[str]
    intro_music: str | None
    intro_music_length_seconds: float
    intro_crossfade_seconds: float
    podcast_format: str
    podcast_length: str
    transcript: dict         # keeps full nested dict (model/device/language/enabled)
    episodes_registry: str   # relative to project root
    wiki_episodes_dir: str   # relative to project root
    xiaoyuzhou: dict         # {podcast_id: str}; dict for future fields

@dataclass(frozen=True)
class EpRef:
    show: str
    ep: int
    # ... methods as in §4

class ShowConfigError(ValueError): pass
class ShowNotFoundError(ShowConfigError): pass
class AmbiguousShowError(ShowConfigError): pass

def load_shows(kb_yaml: dict) -> list[Show]: ...
def default_show(shows: list[Show]) -> Show: ...
def resolve_show(shows: list[Show], show_id: str | None) -> Show: ...
def validate_shows(shows_raw: list[dict]) -> list[Show]:
    """Validate raw show entries from kb.yaml; return typed Show objects.
    Raises ShowConfigError on any violation; error message enumerates all issues."""

# Frontmatter helpers used by episode_wiki's rewritten stub logic:
def ep_ref_to_yaml(ref: EpRef) -> dict: return ref.to_dict()
def parse_ep_ref_field(value: Any) -> EpRef:
    """Strict parse of a dict-form EpRef. Raises on legacy str form."""
```

### 7. Migration — `/kb migrate`

**Command:** `/kb migrate [--show-id <id>] [--show-title <title>] [--dry-run]`

New subcommand on the existing `/kb` skill. Converts a single-show KB to multi-show in place, atomically.

**Detection:** If `kb.yaml` has `integrations.shows`, already migrated — report and exit 0.

**Interactive prompts (if not given via flags):**
- `--show-id` — default `quanzhan-ai` for the known brand; ask user to confirm/change. Validated against the slug regex.
- `--show-title` — default from `integrations.xiaoyuzhou.podcast_title` if present, else infer from `integrations.notebooklm.podcast.brand` if present, else prompt.

**Algorithm:**

1. Snapshot kb.yaml into `<project>/.kb-migration-<timestamp>/kb.yaml.before`.
2. Build the new `shows[0]` entry by moving these fields from their current locations into it:
   - From `integrations.notebooklm.podcast`: `hosts`, `extra_host_names`, `intro_music`, `intro_music_length_seconds`, `intro_crossfade_seconds`, `format` (→ `podcast_format`), `length` (→ `podcast_length`), `transcript`.
   - From `integrations.notebooklm`: `language`.
   - From `integrations.xiaoyuzhou`: `podcast_id` (→ nested as `shows[0].xiaoyuzhou.podcast_id`), `episodes_registry`.
3. Set `shows[0].id`, `title`, `description` (from the user-confirmed flags).
4. Set `shows[0].default: true`.
5. Set `shows[0].wiki_episodes_dir: wiki/episodes/<show-id>`.
6. Write the new `kb.yaml` to staging.
7. For each `wiki/episodes/ep-<N>-<slug>.md`: plan a move to `wiki/episodes/<show-id>/ep-<N>-<slug>.md` (into staging mirror).
8. Parse the old episode article's `index:` block. For any `prior_episode_ref: <int>`, rewrite to `{show: <show-id>, ep: <int>}`. For any body wikilinks matching `[[wiki/episodes/ep-N-<slug>]]`, rewrite to `[[wiki/episodes/<show-id>/ep-N-<slug>]]`.
9. For every wiki article with `status: stub`: rewrite `created_by: ep-N` → `{show: <id>, ep: N}`, same for `last_seen_by`, `best_depth_episode`. Rewrite `referenced_by: [ep-1, ep-2]` list-of-str → list-of-dicts.
10. For every wiki article with `episodes:` frontmatter field (none today; future-proofing for the back-ref spec): leave alone if already dict form; migrate from legacy str form if present.
11. Run validation on the staged tree: `load_shows()` parses the new kb.yaml cleanly; `scan_episode_wiki()` (updated for new format) parses every staged episode article.
12. Atomic commit phase: `os.replace` every staged file into its final location. Order: (a) stub updates first, (b) episode articles (their wikilinks now resolve to real stubs at new paths), (c) kb.yaml last — if anything fails before kb.yaml swap, no downstream skill is confused.
13. If `--dry-run`, skip step 12 and report what would change.
14. Write `.kb-migration-<timestamp>.log` with summary (count of files changed, before/after kb.yaml diff).

**Idempotency:** Rerunning on an already-migrated KB: step 1 detects `shows` exists, exits clean.

**Failure handling:** If validation (step 11) fails, abort; staging dir is preserved for debugging. Commit phase failures (step 12) are rare (atomic os.replace on same filesystem); surface the state clearly but don't attempt rollback.

### 8. Skill behavior changes

#### kb-publish

- `_make_haiku_call`, `orchestrate_episode_index`, `index_episode_transactional`, `judge_candidate_episode` — accept `show: Show` argument. Internal dict passes `{show, ep}` for every ref. Validate slugs in the new `wiki/episodes/<show>/` pattern.
- `backfill_index.py` — read `shows` config, resolve `--show`, load the show's `episodes_registry`, pass show context through. The SKILL.md step 8c (index episode at publish time) uses the show that the audio's registry entry already knows.
- `/kb-publish` and `/kb-publish backfill-index` accept `--show <id>` flag.

#### kb-notebooklm

- Podcast workflow reads show config on step 1 (preamble) by resolving the requested show. The host pool, intro music, transcript settings all come from the show's own fields.
- Step 4b (confidentiality filter) — unchanged.
- Step 5b (dedup judge) — when building `prior_hits`, scan only THIS show's `wiki/episodes/<show>/` directory. Concepts covered in other shows do NOT count against dedup; each show is its own series.
- Step 6a' (series-bible compilation) — include only THIS show's published episodes in the bible.
- Step 6a'' — intro music probe uses the show's `intro_music` field.
- Step 6k (background agent) — assembled MP3 goes to `<output_path>/podcast-<show-id>-<theme>-YYYY-MM-DD.mp3` (filename stem gains show prefix to avoid collisions when a second show is introduced).
- `/kb-notebooklm podcast --show <id>` resolves the show; otherwise default.
- `/kb-notebooklm status` — accepts `--show <id>` (default: all shows).
- `/kb-notebooklm cleanup` — accepts `--show <id>` (default: all shows, per-show state still isolated).

#### kb-init

- Fresh installs seed `integrations.shows[0]` with `default: true` and prompt for `id`, `title`, `description`, `hosts`. Other per-show fields fall back to sensible defaults (e.g., `transcript.model: large-v3`).
- Default `shows[0].id = "main"` if user doesn't pick one; the CLI still accepts `--show-id`.
- Existing kb-init integrations (xiaoyuzhou, gemini) write their config under the show entry when they need per-show values.

#### kb (the umbrella skill)

- New `/kb migrate` subcommand (section 7).
- The existing workflows (compile, query, lint, evolve) are NOT show-scoped. Wiki content is shared across shows.

### 9. Episode filename stem convention

Current: `podcast-<theme>-YYYY-MM-DD.mp3` for the default show.

After: `podcast-<show-id>-<theme>-YYYY-MM-DD.mp3`. The `<show-id>` segment appears even for single-show deployments (no special case for "the one and only"). Two reasons:
1. Future shows won't need to rename existing files to add their prefix.
2. `ls output/podcast-*` always tells you the show from the filename.

Migration: we do NOT rename existing output MP3 files. The show prefix only appears on newly-generated files. The `podcast-quantization-2026-04-22.mp3` file remains as-is after migration.

However, the **new** EP3 v2 and future episodes will use the new convention (`podcast-quanzhan-ai-quantization-2026-04-22-v3.mp3` or similar).

The `podcast_outputs` record in state also carries the show prefix for new episodes. Old `podcast_outputs` entries (from pre-migration v1 runs) are left alone.

### 10. Error handling

| Condition | Behavior |
|---|---|
| `integrations.shows` absent after migration | Error on any show-scoped command: "Run `/kb migrate` to migrate to multi-show format." |
| `integrations.shows` empty | `ShowConfigError` listing all validation issues. |
| Multiple shows, no default, no `--show` | `AmbiguousShowError` with list of show ids and instructions. |
| `--show <id>` doesn't match any show | `ShowNotFoundError` listing available ids. |
| Episode article has `prior_episode_ref: <int>` (legacy) | On read: log warning "looks like pre-migration data; run `/kb migrate`". Treat as `{show: <default_show_id>, ep: <int>}` for graceful degradation. |
| Stub frontmatter has legacy string form | Same — log + treat as default show's ref. Written back in new form on next update. |
| Two stubs have the same slug but different shows created it | Not possible in practice (stubs are vault-wide; `referenced_by` list just accumulates refs from multiple shows). |
| A show config's `wiki_episodes_dir` points outside `wiki_path` | Validation error. |
| Migrator runs on partially-migrated KB (e.g., kb.yaml migrated but wiki/episodes/ not moved) | Detects by checking `wiki/episodes/*.md` existence at root-level; offers to "resume" migration. Atomic commit in the first run should prevent this, but surface cleanly if it happens. |

### 11. Testing

**Unit tests** (hermetic):

1. `shows.py`:
   - `validate_shows` accepts a valid single-show config; rejects missing `shows[]`, duplicate ids, bad id format, multiple defaults, missing default with multiple shows, duplicate `episodes_registry`, duplicate `wiki_episodes_dir`, bad `wiki_episodes_dir` (outside `wiki_path`).
   - `resolve_show`: explicit id wins; single-show returns the one; default is chosen when multiple; raises on ambiguity and on unknown id.
   - `EpRef.from_any`: dict form parses; legacy str `ep-3` parses with `default_show` kwarg; raises on bad input.
   - `EpRef.wikilink_stem` produces the correct nested path.
2. `episode_wiki.py` (updates):
   - `scan_episode_wiki` walks `wiki/episodes/<show>/*.md` subdirs; `strict=False` lenient skip on malformed files still works.
   - `compute_stub_update` produces dict-form `created_by`/`last_seen_by`/`best_depth_episode`/`referenced_by`.
   - `render_stub` emits dict-form frontmatter fields.
   - `render_episode_wiki`'s `index.concepts[].prior_episode_ref` is dict.
3. `migrate_multi_show.py`:
   - Detects already-migrated KB, exits idempotently.
   - Dry-run produces correct report without modifying anything.
   - Actual migration transforms a fixture KB correctly.
   - Validation failure aborts without modifying anything.
   - Post-migration, `scan_episode_wiki` and `load_shows` both succeed on the output.

**Integration tests** (end-to-end on real KB):

4. Run `/kb migrate --dry-run` against the actual KB and confirm planned changes.
5. Run `/kb migrate` against the actual KB.
6. Re-run `/kb-publish backfill-index --episode 1 --show quanzhan-ai` and confirm it finds the show, finds the episode article in the new location, and works.
7. Verify `/kb-notebooklm podcast` still generates with the default show auto-selected (no `--show` argument).

**Procedural verification:**

- Before migration: commit the KB state. After migration: compare diff, inspect a sample stub, inspect EP1/EP2 articles, inspect the new kb.yaml.
- Run full unit test suite (141 + new show tests).

## Scope, non-goals, and open questions

**In scope:**
- `shows.py` new module, `EpRef` value object, validators.
- `episode_wiki.py` updates to accept EpRef throughout.
- `backfill_index.py` `--show` flag.
- `kb-notebooklm` SKILL.md changes (step 1, 5b, 6a', 6a'', 6k).
- `kb-publish` SKILL.md changes (step 8c).
- `kb-init` SKILL.md changes (seed `shows[0]`).
- `kb` SKILL.md gains `migrate` subcommand.
- Migrator script `migrate_multi_show.py`.
- ~40 new unit tests.

**Explicitly out of scope:**
- Episode back-references on non-episode wiki articles (next spec).
- Wiki articles as NotebookLM sources (third spec).
- Cross-show anything (search, dedup, analytics).
- Repointing old MP3 filenames to include show prefix (only new files get the prefix).

**Open questions:** None. All design questions resolved during brainstorm.

## References

- Earlier features:
  - `docs/superpowers/specs/2026-04-20-podcast-intro-hosts-transcript-design.md` — transcripts + intro music
  - `docs/superpowers/specs/2026-04-21-episode-index-and-dedup-design.md` — episode index
- This is the FIRST of three planned specs in the "knowledge-graph-aware podcasting" series. Next: wiki-episode-backrefs. Then: wiki-as-source.
