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
      wiki_episodes_dir: episodes/quanzhan-ai    # WIKI-ROOT-relative, not project-root-relative
      xiaoyuzhou:
        podcast_id: "69ddba132ea7a36bbf1efa77"
```

### 2. Validation rules on config load

- `integrations.shows` MUST exist and be a non-empty list.
- Every `id` matches `^[a-z][a-z0-9\-]{1,31}$` (URL-safe slug, 2-32 chars).
- `id` values are unique across all shows.
- `default: true` is optional on every show, regardless of count. If present on 2+ shows: config validation error (`ShowConfigError`, "only one show may be marked default"). If absent from all shows: permitted. The flag is advisory — neither resolver consults it. (Earlier drafts required exactly-one-default for multi-show; this has been loosened because the resolvers don't use the flag.)
- `episodes_registry` paths are unique across shows.
- `wiki_episodes_dir` paths are unique across shows.
- `xiaoyuzhou.podcast_id` (optional per show) is unique when present.
- `episodes_registry` is a relative path; resolved against the project root (directory containing `kb.yaml`).
- `wiki_episodes_dir` is **NOT configurable — fixed as `episodes/<show-id>`, wiki-root-relative**. Simplifies the contract: physical path = `wiki_path / episodes / <show-id>`, wikilink stem = `wiki/episodes/<show-id>/ep-N-<slug>`. The two are identical in structure (just different roots), eliminating the "what if they differ?" edge case. Earlier drafts made this configurable; removed for simplicity. The `wiki_episodes_dir` field is still stored in the Show config for explicitness (making the data model transparent) but validation REQUIRES it to equal `episodes/<show-id>`.
- Validation errors list every violation at once (not one-at-a-time).

### 3. Resolution semantics

Resolution is governed by a single truth table. Three command kinds × two KB states:

| Command kind | Examples | single-show + no `--show` | single-show + `--show X` | multi-show + no `--show` | multi-show + `--show X` |
|---|---|---|---|---|---|
| **mutating** — creates/modifies a show's artifacts | `podcast`, `publish`, `backfill-index`, `quiz`, `digest`, `report`, `research-audio` | implicit: sole show | matched show or `ShowNotFoundError` | **`AmbiguousShowError`** | matched show |
| **read-all** — iterates per-show, no wrong-show risk | `status`, `cleanup` | sole show | restrict to that show | iterate every show | restrict to that show |
| **tree-admin** — operates on the entire project config, independent of any one show | `migrate` | (N/A — no resolver) | (N/A) | (N/A) | (N/A) |

`migrate` is explicitly **tree-admin**: it runs before any show is resolvable (the whole point is to create the `shows[]` config) and it is by definition KB-wide. It accepts `--show-id` / `--show-title` flags to name the default show being created, not to select among existing ones. Tree-admin commands never call the resolvers.

`cleanup` is **read-all**: it prunes stale per-show records independently; there is no wrong-show risk. Running with no `--show` in a multi-show KB applies cleanup rules independently to each show.

Two resolver entry points implement this. No other resolver is part of the public API.

```python
def resolve_show_for_mutation(
    shows: list[Show],
    show_id: str | None,
) -> Show:
    """Resolver for mutating commands.

    single-show + None → shows[0]
    single-show + explicit → matched (or ShowNotFoundError)
    multi-show + None → AmbiguousShowError
    multi-show + explicit → matched (or ShowNotFoundError)

    The `default: true` flag is NEVER consulted here. Mutating paths
    refuse to guess which show.
    """

def resolve_show_for_read(
    shows: list[Show],
    show_id: str | None,
) -> Show | None:
    """Resolver for read-all commands.

    single-show + None → shows[0]           (sole-show KB gets implicit resolution)
    single-show + explicit → matched (or ShowNotFoundError)
    multi-show + None → None                (signal: caller must iterate all shows)
    multi-show + explicit → matched (or ShowNotFoundError)
    """
```

The `default: true` flag exists for future use (e.g., web UIs, auto-suggest, an "upcoming feature" to emit a warning when you forget `--show`). It is NOT consulted by either resolver.

Single-show KBs (99% of usage) see zero friction: no `--show` needed anywhere.

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
        """Return the path-without-.md used inside [[ ]] wikilinks.

        The Obsidian wikilink stem is CONVENTIONAL — always `wiki/episodes/<show>/ep-<N>-<slug>`,
        regardless of the show's `wiki_episodes_dir` config value. Rationale:
        Obsidian users click on `[[wiki/episodes/...]]` links and expect a
        predictable path. The `wiki_episodes_dir` config controls the PHYSICAL
        filesystem path (resolved against wiki_path); the wikilink stem is a
        separate concept — what appears inside `[[ ]]` in markdown.

        For filesystem path construction, callers use
        `resolve_episode_wikilink(ref, shows_by_id, wiki_path)` which DOES
        consult `wiki_episodes_dir`. Two different helpers for two different
        purposes.
        """
        return f"wiki/episodes/{self.show}/ep-{self.ep}-{slug}"

    @classmethod
    def from_dict(cls, d: dict) -> "EpRef":
        """Strict parse of a dict-form EpRef. Raises on missing fields or wrong types.
        This is the ONLY parser used by post-migration code."""
        if not isinstance(d, dict):
            raise ValueError(f"EpRef expects a dict, got {type(d).__name__}")
        show = d.get("show")
        ep = d.get("ep")
        if not isinstance(show, str) or not show:
            raise ValueError(f"EpRef.show must be a non-empty string: {d}")
        if not isinstance(ep, int) or ep < 1:
            raise ValueError(f"EpRef.ep must be a positive int: {d}")
        return cls(show=show, ep=ep)

    @classmethod
    def from_legacy(cls, value, *, default_show: str) -> "EpRef":
        """Parse a legacy str 'ep-N' or bare int N as the default show's ref.
        ONLY used by the migrator — not by post-migration runtime code.
        """
        if isinstance(value, int):
            return cls(show=default_show, ep=value)
        if isinstance(value, str):
            m = re.match(r"^ep-(\d+)$", value)
            if not m:
                raise ValueError(f"legacy ref must match 'ep-N': {value!r}")
            return cls(show=default_show, ep=int(m.group(1)))
        raise ValueError(f"legacy ref must be str or int: {value!r}")
```

**No runtime fallback for legacy refs.** Post-migration code only accepts dict-form `{show, ep}`. If a runtime reader encounters a bare int or `ep-N` string in stub frontmatter or `prior_episode_ref`, it raises `MigrationRequiredError` with a message pointing at `/kb migrate`. This is safer than silently treating unknowns as the default show — in a multi-show KB, that assumption can be wrong.

Only the migrator itself uses `from_legacy()`.

YAML / JSON serialization: always the dict form `{show, ep}`. No legacy strings are accepted by post-migration code (legacy parsing is only in the migrator).

Filesystem: episode article lives at `<wiki>/episodes/<show>/ep-<N>-<slug>.md`. Obsidian wikilinks use the same path (without `.md`): `[[wiki/episodes/<show>/ep-<N>-<slug>]]`.

Prompt text: the series-bible rendering in podcast-tutor.md's `{series_context}` uses human-readable form: `"EP1 (全栈AI): GPU Computing & CUDA (intro)"` — show title parenthesized after EP number. Single-show KBs can omit the show suffix when all episodes in context are from the same show as the current one (implementation detail: render the full form only when prior episodes include any from a different show; otherwise keep the current terse form).

### 4a. `IndexedEpisode` and coverage-map must carry `show`

Current `IndexedEpisode` (from `episode_wiki.py`) has `episode_id: int`. After this spec, every episode record is show-aware end-to-end:

```python
@dataclass
class IndexedEpisode:
    show: str                     # NEW
    episode_id: int
    title: str
    # ... existing fields
```

And `concepts_covered_by_episodes()` returns coverage keyed by slug, with each hit carrying both `show` and `ep_id`:

```python
# before
coverage[slug] = [{"ep_id": 1, "depth": "deep-dive", ...}, ...]

# after
coverage[slug] = [{"show": "quanzhan-ai", "ep_id": 1, "depth": "deep-dive", ...}, ...]
```

**EVERY index-pipeline read is scoped to the resolved show — never cross-show.** This resolves the apparent tension with the "cross-show dedup out of scope" non-goal: we keep the data structures show-aware (so the code is ready when we later want cross-show features), but the current kb-notebooklm step-5b call scopes every read to the current show. Specifically:

- `scan_episode_wiki(wiki_path, show, strict=False)` — new signature. Takes `wiki_path` (the absolute path of the Obsidian wiki root, from `integrations.notebooklm.wiki_path`) and a `Show`. Resolves `show.wiki_episodes_dir` against `wiki_path` (NOT `project_root`) to get the absolute episode directory. Only walks that directory. Never other shows' dirs. The legacy signature `scan_episode_wiki(wiki_dir)` is removed; all callers must pass `wiki_path + show`.
- During migration validation, the check is performed per show: `for show in configured_shows: scan_episode_wiki(wiki_path, show, strict=True)`. `wiki_path` is resolved from the staged kb.yaml; during staged validation this points at the live `wiki_path` (since wiki content IS staged under staging_root/wiki but `wiki_path` in the staged kb.yaml may still be absolute — the migrator translates it to `staging_root/wiki` for validation-time reads only). Post-commit validation uses the live `wiki_path` as-is.
- `concepts_covered_by_episodes(episodes)` — the function itself is show-agnostic (just aggregates), but the `episodes` list passed in comes from the filtered `scan_episode_wiki` above.
- `compute_depth_deltas(concepts, coverage_map)` — receives a coverage_map built only from the current show's episodes. Emits `prior_episode_ref` as `{show, ep}` dict (see below). Function behavior: no mixing inside, but output shape changes.
- Recent-episode context in the `episode-wiki-extract` prompt: only this show's episodes, most-recent-N excluding the current episode.
- Dedup judge `prior_hits`: only this show's hits. The Haiku prompt includes show title for future-proofing but in single-show / same-show-context runs it's redundant.

The `EpRef` dict carries `show` always, so if we later introduce a cross-show dedup mode (explicitly, via a flag), the data is ready. But **nothing in this spec's scope reads across shows**.

The episode-article `index.series_links.builds_on[]` holds list of EpRef dicts. Migration rewrites this field. The episode-wiki-extract prompt instructs Haiku to emit `series_links.builds_on` as list of `{show, ep}` dicts — and since the prompt only includes same-show episodes in the context, Haiku has no way to emit a cross-show ref in practice.

`resolve_concept_candidate()` — doesn't use episode refs directly. Unaffected.

`compute_depth_deltas()` signature unchanged (still `(concepts, coverage_map)`), but the `coverage_map` type changes from `{slug: [{ep_id, depth, ...}]}` to `{slug: [{show, ep_id, depth, ...}]}`. The function logic still picks the "deepest prior hit" to compute `depth_delta_vs_past`. Its OUTPUT for `prior_episode_ref` changes:

**Before** (legacy):
```python
out_concept["prior_episode_ref"] = deepest["ep_id"]  # int
```

**After** (this spec):
```python
out_concept["prior_episode_ref"] = {"show": deepest["show"], "ep": deepest["ep_id"]}  # EpRef dict
```

**Mixed-show coverage_map policy:** `compute_depth_deltas()` expects a `coverage_map` built for a single show. If the function detects multiple distinct `show` values across all hits, it raises `MixedShowCoverageError`. This catches a class of caller bugs (accidentally passing a cross-show coverage map) at the earliest possible point, rather than silently producing nondeterministic output. The kb-notebooklm step 5b always builds its coverage_map from a single `scan_episode_wiki(show=current_show)`, so this never fires in normal flow.

Tie-breaking when two hits have the same deepest depth (and by policy above, same show too): lowest `ep_id` wins.

Tests verify:
- Output shape for every code path (new / deeper / same / lighter).
- Depth tie-break by lowest ep_id within the same show.
- Mixed-show coverage_map raises `MixedShowCoverageError`.
- `series_links.builds_on[]` goes through the same {show, ep} dict treatment in both the render path (`render_episode_wiki`) and the parse path (`scan_episode_wiki`), via the shared `parse_ep_ref_field` contract.

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
| Dedup-judge prompt prior_hits shape | `[{ep_id: int, depth, key_points}]` per slug | `[{show: str, ep_id: int, depth, key_points}]` per slug — SAME flat-dict shape as coverage_map (§4a), NOT nested EpRef. This is canonical. The "`prior_hits[].ep_id` dict" phrasing in older drafts was wrong; hits carry `show` + `ep_id` as sibling keys. |
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
    episodes_registry: str   # relative to project root (directory containing kb.yaml)
    wiki_episodes_dir: str   # relative to WIKI root (integrations.notebooklm.wiki_path); always equals "episodes/<id>"
    xiaoyuzhou: dict         # {podcast_id: str}; dict for future fields

@dataclass(frozen=True)
class EpRef:
    show: str
    ep: int
    # ... methods as in §4

class ShowConfigError(ValueError): pass
class ShowNotFoundError(ShowConfigError): pass
class AmbiguousShowError(ShowConfigError): pass
class UnknownShowError(ShowConfigError): pass
class MigrationRequiredError(RuntimeError): pass

def load_shows(kb_yaml: dict, project_root: Path) -> list[Show]:
    """Load and validate `integrations.shows[]` from parsed kb.yaml dict.

    `project_root` is the directory containing kb.yaml. Used to resolve
    `episodes_registry` (project-root-relative). Note that `wiki_episodes_dir`
    is WIKI-root-relative (not project-root), resolved against
    `integrations.notebooklm.wiki_path` — so this function reads wiki_path
    from kb_yaml and validates `wiki_episodes_dir` against that, not against
    project_root."""

def validate_shows(
    shows_raw: list[dict],
    *,
    project_root: Path,
    wiki_path: Path,
) -> list[Show]:
    """Validate raw show entries; return typed Show objects.

    Requires project_root (for resolving relative paths) and wiki_path
    (for validating wiki_episodes_dir is under it).
    Raises ShowConfigError on any violation; error message enumerates all issues."""

def resolve_show_for_mutation(shows: list[Show], show_id: str | None) -> Show:
    """See §3. Hard error on ambiguous."""

def resolve_show_for_read(shows: list[Show], show_id: str | None) -> Show | None:
    """See §3. Returns None on ambiguous (signaling iterate-all)."""

# Frontmatter helpers used by episode_wiki's rewritten stub logic:
def ep_ref_to_yaml(ref: EpRef) -> dict: return ref.to_dict()

def parse_ep_ref_field(value: Any, *, known_shows: set[str]) -> EpRef:
    """Strict parse of a dict-form EpRef with REFERENTIAL validation.

    Raises on:
      - legacy str / int (MigrationRequiredError)
      - missing/wrong-typed fields (ValueError)
      - ref.show not in known_shows set (UnknownShowError)

    `known_shows` = set of `show.id` values loaded from kb.yaml. Every
    call site MUST pass this — shape-only validation is insufficient.
    """

def resolve_episode_wikilink(
    ref: EpRef,
    shows_by_id: dict[str, Show],
    wiki_path: Path,
) -> str:
    """Resolve an EpRef to a full wikilink stem like
    'wiki/episodes/<show-id>/ep-<N>-<slug>'.

    Requires looking up the episode article on disk to find its filename
    (which includes the slug). Strategy:
      1. Look in wiki_path / shows_by_id[ref.show].wiki_episodes_dir.
      2. Find the single file matching `ep-<ref.ep>-*.md`.
      3. Return its Obsidian wikilink stem as `wiki/episodes/<ref.show>/ep-<ref.ep>-<slug>` (conventional vault-relative form; note this stem is independent of the physical `wiki_episodes_dir` value — it matches Obsidian's conventional layout).

    Raises EpisodeNotFoundError if no matching file exists, or if multiple
    match (indicates a broken wiki).

    Used by render_episode_wiki when emitting body wikilinks for
    series_links.builds_on, and by the migrator when converting legacy
    wikilinks that already contain the full stem.
    """

def validate_body_wikilinks(
    text: str,
) -> list[str]:
    """Return every wikilink in the text that matches the legacy flat form
    `[[wiki/episodes/ep-N-<slug>]]` (no show subdir). Empty list = clean.

    This is a distinct check from `parse_ep_ref_field`; EpRef fields are
    structured values in YAML frontmatter, whereas body wikilinks are
    arbitrary prose embedded in markdown. Callers validate both separately.
    """
```

**No `default_show()` or generic `resolve_show()` in the public API.** Earlier drafts advertised these; removed. Use the two explicit resolvers only.

**Referential validation is mandatory.** Every `EpRef` parse call site (runtime reads of stub frontmatter, runtime reads of episode articles, migrator strict validation, Haiku response parsing) MUST pass `known_shows`. If a ref points at an unknown show id, raise `UnknownShowError`. This catches Haiku hallucinations, migrator bugs, and hand-editing mistakes.

### 7. Migration — `/kb migrate`

**Command:** `/kb migrate [--show-id <id>] [--show-title <title>] [--dry-run]`

New subcommand on the existing `/kb` skill. Converts a single-show KB to multi-show in place, atomically.

**Detection (tri-state):**

The migrator classifies the KB into one of three states before doing anything. Detection is always a **full-tree scan** — never samples:

- **unmigrated**: `kb.yaml` has no `integrations.shows`, AND no `wiki/episodes/<show-id>/` subdirs exist. Full migration runs.
- **partially_migrated**: any of:
  - `kb.yaml` has no `integrations.shows` BUT `wiki/episodes/<show-id>/*.md` exist somewhere.
  - `kb.yaml` has `shows[]` but flat `wiki/episodes/ep-*.md` files still exist at the root.
  - A `.commit-in-progress` marker exists in any `.kb-migration-*/` dir.
  - Any stub or concept article has a legacy str/int ref when parsed with `parse_ep_ref_field(known_shows=<configured-shows>)`.
  - Any staged file in the `shows` known_shows set points at an unknown show id.
- **fully_migrated**: the KB must pass **exactly the same checks as Phase B validation** (see §7 Phase B) on the LIVE tree — not a weaker subset. Specifically: `load_shows(live_kb_yaml, project_root)` succeeds; per-show `scan_episode_wiki(wiki_path, show, strict=True)` succeeds for every show (wiki_path is live, not staged); every frontmatter EpRef field parses via `parse_ep_ref_field` with `known_shows`; `validate_body_wikilinks` returns empty for every `.md` file; state file loads under the new shape (reads `shows.<id>.*` keys, no top-level `runs[]` / `notebooks[]` / `last_*`); **every sidecar manifest at `<output_path>/*.manifest.yaml` AND `<output_path>/notebooklm/*.manifest.yaml` has a `show:` field with value in `known_shows`**. If any check fails, the KB is `partially_migrated`. Exits with `status: already migrated` only when ALL checks pass.

The full classification (file counts, any detected legacy refs, partial paths) is logged to `.kb-migration-<timestamp>/detection.log` for audit.

**Resume behavior:** on `partially_migrated`, the migrator recomputes the staging plan from current disk state (not from the snapshot of the original kb.yaml, which may or may not still exist), re-runs validation, and continues the atomic commit phase from the first un-committed step. Re-running on `fully_migrated` is idempotent.

**Interactive prompts (if not given via flags):**
- `--show-id` — default `quanzhan-ai` for the known brand; ask user to confirm/change. Validated against the slug regex.
- `--show-title` — default from `integrations.xiaoyuzhou.podcast_title` if present, else infer from `integrations.notebooklm.podcast.brand` if present, else prompt.

**Guiding invariant (revised):** we do NOT promise "pre-swap crashes leave the tree runnable by pre-migration readers" — that invariant is impossible because shared wiki/stub files get rewritten atomically and become unreadable by old code once they're in-place. Instead, the real invariant is:

> **"The migrator can always resume to a valid end state from any crash point."**

Achieved by: (a) fully staging every changed file under `.kb-migration-<timestamp>/`, (b) strict-validating the entire staged tree before ANY live commit, (c) a single-phase commit that moves all files into place in a deterministic order, (d) writing a `.commit-in-progress` marker file so a rerun can detect and resume a partial commit.

**Algorithm — single deterministic phase machine:**

**Concurrency lock (mandatory) + preflight idle check — acquire-then-verify ordering:**

A file-based lock at `<project>/.kb-mutation.lock` is a **KB-wide mutex** held by ANY mutating command — not just migration. Every kb-notebooklm / kb-publish / backfill-index / migrate command acquires this lock before taking any write-action, releases after. The lock file contains `{pid, command, start_time}`.

**Detached background agents (podcast generation's 90-min NotebookLM wait + transcribe):** these run outside the foreground command. They MUST also acquire the lock before writing state/sidecars/output files. Specifically: when the detached agent is ready to `os.replace` its output MP3 or update `.notebooklm-state.yaml`, it acquires `.kb-mutation.lock` via the same context manager. If the lock is held by migration, the agent waits (with a generous timeout — the agent just finished a 60-min generation, 60 more seconds of waiting is fine). Migration's idle-check sees the agent's pending `runs[]` entry and refuses to start until the agent finishes and cleans up. This closes the race completely: migration cannot start while ANY writer is in flight, even detached ones.

Migration ordering (strict):

1. **Acquire** `.kb-mutation.lock` FIRST, before any reads. If the lock is held by another kb command, refuse with `LockBusyError` pointing at the holder.
2. **While holding the lock**, run the idle check. Schema depends on state file format:
   - If legacy flat format: scan top-level `runs[]` and `notebooks[]` for `status: pending`.
   - If new show-scoped format: scan `shows.<id>.runs[]` and `shows.<id>.notebooks[]` for `status: pending` across every show.
   If any found, release the lock and refuse with `PendingWorkError` listing them. (Pending state means a background agent is expected to finalize that record. Combined with the rule that detached agents also acquire the lock, this guarantees no writer is in flight when migration proceeds.)
3. **If idle, proceed with Phases A-D while holding the lock.**

This eliminates the gap between idle-check and lock-acquire. Other commands that try to start during migration hit `LockBusyError` immediately; no race window.

Any kb command that cannot acquire the lock within 5 seconds exits with a clear message. The lock file is cleaned up by a context manager on normal exit AND on SIGINT/SIGTERM (the context manager registers a signal handler). Stale locks (PID no longer running) are detected and removed with user confirmation.

**Paths outside the project root:** `wiki_path` and `output_path` may be absolute paths outside `project_root` (e.g., `/Users/dragon/Documents/MLL/wiki`). Phase B validation must NOT assume these live under `staging_root`. Instead:

- Staged config files (`kb.yaml`, `.notebooklm-state.yaml`) live under `staging_root`.
- Staged wiki content lives under `staging_root/wiki/` (relative to project root, matching how the live tree sees it).
- Sidecars are migrated **IN PLACE**, not through staging (because `output_path` may be absolute / outside project root). The migrator:
  1. Snapshots every live sidecar into `<migration-dir>/before/sidecars/` (preserving path structure).
  2. Rewrites each sidecar atomically (temp file + os.replace) adding `show: <default-show-id>` if missing.
  3. Validates the rewritten sidecars: `show:` present and in `known_shows`. Failure → restore from `before/sidecars/` and abort.
  
  This happens during Phase A (plan) / Phase B (validate) as an in-place step; sidecars are NOT listed in the staging-dir tree. Correspondingly, Phase B step 5's sidecar check reads from LIVE `<output_path>`, not from `staging_root/output/`.
- The `staging_root/output/...` reference in Phase B step 5 is removed: sidecar validation operates on the LIVE `output_path`, not on staged paths.

Phase A — **Plan** (no disk writes to live tree):

1. Detect current state: `unmigrated`, `partially_migrated`, or `fully_migrated` (§detection below). If `fully_migrated`, exit 0.
2. Snapshot live kb.yaml, .notebooklm-state.yaml, and every file targeted for rewrite into `<project>/.kb-migration-<timestamp>/before/`.
3. Build the staging tree at `<project>/.kb-migration-<timestamp>/staging/`:
   - New `kb.yaml`.
   - New `.notebooklm-state.yaml` (wrapped under `shows.<id>.*`).
   - For each old `wiki/episodes/ep-<N>-<slug>.md`: rewritten version at `staging/wiki/episodes/<show-id>/ep-<N>-<slug>.md`.
   - For each stub / concept article touched: rewritten version at `staging/<same-path>`.
   - (Sidecar manifests are NOT staged — they are migrated in-place as a separate sub-phase; see "Paths outside the project root" above and "Phase A-bis (sidecar in-place)" below.)
4. Build a plan manifest `<migration-dir>/plan.yaml` listing every source→destination pair (including deletes of old flat `wiki/episodes/ep-*.md`).

Phase A-bis — **Sidecar in-place migration** (in-place disk writes, separate from main staging):

Sidecars get migrated directly on disk — `output_path` may be absolute/outside project_root, so staging would require path translation that's hard to keep consistent. In-place is simpler and safer:

4a. Acquire the mutation lock (already held from §before Phase A).
4b. Snapshot every live sidecar to `<migration-dir>/before/sidecars/` preserving the relative path under `output_path`. This is the recovery source.
4c. For each sidecar missing `show:`: atomic temp-file-rewrite + `os.replace` adding `show: <default-show-id>`.
4d. Log each rewrite to `<migration-dir>/sidecars.log` with (path, before_sha256, after_sha256).
4e. Validate the rewritten sidecars (Phase B step 5's sidecar check). If any fail, restore every rewritten sidecar from `before/sidecars/` using the log; abort migration.

Phase A-bis completes before Phase B runs. The resulting tree is: live sidecars migrated, staging tree holds every other changed file.

Phase B — **Validate** (Phase A's no-disk-writes promise applies to Phase A only; Phase A-bis has already committed sidecars in-place):

Each check below uses the documented public signatures from §6.

5. Run full-tree validation on staging (`staging_root = <migration-dir>/staging`):
   - **Config:** Parse `staging_root/kb.yaml` → dict `kb`. Call `load_shows(kb, project_root=staging_root)`. All §2 rules must pass. Capture the resulting `shows_list` and `known_shows = {s.id for s in shows_list}`.
   - **Per-show wiki scan:** For each `show` in `shows_list`:
     - Call `scan_episode_wiki(wiki_path=staging_wiki_path, show=show, strict=True)`. (`staging_wiki_path` = `staging_root/wiki` during pre-commit validation, live `wiki_path` during post-commit validation.) Every episode article in that show's dir parses cleanly. All `prior_episode_ref` and `series_links.builds_on` entries are dict-form EpRef and pass `parse_ep_ref_field(ref, known_shows=known_shows)`.
   - **Stub / concept frontmatter EpRef fields:** For every `.md` file under `staging_root` excluding `staging_root/wiki/episodes/**`: parse frontmatter. For each of `created_by`, `last_seen_by`, `best_depth_episode`, entries in `referenced_by[]`, and entries in any `episodes[]` array: call `parse_ep_ref_field(value, known_shows=known_shows)`. If any raises, fail validation.
   - **Body-prose wikilink sweep** (distinct check from EpRef parsing): For every `.md` file under `staging_root` (wiki content AND episode articles): grep for the regex `\[\[wiki/episodes/ep-\d+-` (flat form, no show subdir). Zero matches required. This catches stub prose like `Introduced in [[wiki/episodes/ep-1-...]]` and body wikilinks in episode articles.
   - **State file:** `staging_root/.notebooklm-state.yaml` must load via the dual-format loader AND, after loading, expose its data under `shows.<known-show>.*` keys (post-migration shape). Legacy flat shape at the top level must be absent.
   - **Sidecars:** Since sidecar rewrites happen in-place rather than through staging (paths may be absolute / outside project root), sidecar validation reads from the LIVE `<output_path>/*.manifest.yaml` and `<output_path>/notebooklm/*.manifest.yaml` after the in-place rewrite step. Each must have a `show:` field whose value is in `known_shows`. Missing or unknown-show sidecars fail validation. On failure, sidecars are restored from `<migration-dir>/before/sidecars/` (migrator snapshots every sidecar into `before/` before the rewrite). This validation happens AFTER the sidecar rewrites complete but BEFORE Phase C.
6. If any validation fails, abort with full report listing every failure (not first-failure-only). Staging dir preserved for debugging. No live writes.

Phase C — **Commit** (disk writes; idempotent if resumed):

**Copy-then-verify, never move-and-lose.** `os.replace` moves the staging file away, so a crash between the move and the counter update leaves a stale staging tree with no record of what got committed. Instead:

7. Write `<migration-dir>/.commit-in-progress` marker containing the plan manifest.
8. Sequentially for each plan entry:
   - 8a. `os.makedirs(parent_of_dest, exist_ok=True)` for any new parent dir.
   - 8b. **Copy** the staging content to a sibling-of-dest temp file (`<dest>.<timestamp>.tmp`). Do NOT touch the staging file yet — it stays intact as our recovery source.
   - 8c. `os.replace(<dest>.tmp, <dest>)` — atomic on local filesystems. Content is now live.
   - 8d. Verify the live file (byte-equal to staging content or, equivalently, re-read through the same parser used in phase B and confirm it validates).
   - 8e. Append a per-entry done-record to `<migration-dir>/commit.log` after 8d succeeds: `{path, staging_sha256, live_sha256, timestamp}`.
9. For delete operations (old flat `wiki/episodes/ep-*.md` files): after the corresponding nested copy is live AND in the done-log, `os.remove` the old flat file, then append a delete done-record.
10. `kb.yaml` commits last (same copy-then-verify pattern). It is committed last as a pragmatic ordering so live readers see mismatched state for the shortest window possible.
11. Delete `.commit-in-progress`.
12. Run post-commit validation on the live tree (same as phase B on live paths). Any failure: surface with `POST-COMMIT FAILURE: <details>`, preserve `.kb-migration-<timestamp>/` for manual recovery.

**Crash-recovery:** a rerun inspects `commit.log`:
- For each entry in the log: verify the live file's sha256 still matches the recorded `live_sha256`. If yes, entry is done, skip. If no (live was modified post-commit — unexpected but possible), abort and surface the discrepancy.
- For each staging entry NOT in the log: commit it (phase 8 path). The staging file is the authoritative source for un-logged entries.
- For each delete entry not in log: if dest exists at old path AND nested-copy entry is in log, perform the delete and log it. Otherwise skip (this means the nested copy isn't yet committed, so the delete is premature).

This makes commit granular at the per-file level and distinguishes "not started" from "already moved but not checkpointed" via the log + sha256 fingerprints.

Phase D — **Logging:** Write `.kb-migration-<timestamp>.log` summarizing file count by category, before/after kb.yaml diff.

**Resume:** rerunning `/kb migrate` after a crash finds `.commit-in-progress` and resumes via the per-entry commit.log (see Phase C crash-recovery). If no `.commit-in-progress` but tri-state detects `partially_migrated`, rebuild a new plan from the current on-disk state and re-run phases B+C.

**Flag behavior on resume:** if `kb.yaml` already has a `shows[]` entry and `--show-id` / `--show-title` flags are passed, they MUST match the existing default show. A mismatch raises `ResumeMismatchError` ("existing show id is X; flag requested Y; refusing to proceed"). No flags on resume → use existing values. This prevents accidentally renaming the show mid-migration.

**If `--dry-run`:** **`--dry-run` must be fully non-destructive.** Phase A-bis (sidecar in-place rewrites) is SKIPPED — sidecars are validated in-memory by computing the would-be rewrite without touching disk. Phase C (commit) is SKIPPED. Phase A still creates the `<migration-dir>/` staging tree and snapshots so the user can audit the plan, but NO live file is modified. Report the full diff: file counts, paths, kb.yaml before/after, sidecar count. Test: run `--dry-run` on a live fixture, assert every live file's `mtime` is unchanged.

### 8. Skill behavior changes

#### kb-publish

- `_make_haiku_call`, `orchestrate_episode_index`, `index_episode_transactional`, `judge_candidate_episode` — accept `show: Show` argument. Internal dict passes `{show, ep}` for every ref. Validate slugs in the new `wiki/episodes/<show>/` pattern.
- `backfill_index.py` — read `shows` config, resolve `--show`, load the show's `episodes_registry`, pass show context through. The SKILL.md step 8c (index episode at publish time) uses the show that the audio's registry entry already knows.
- `/kb-publish` and `/kb-publish backfill-index` accept `--show <id>` flag.

**kb-publish sequencing (REQUIRED):**

The skill MUST resolve the effective show BEFORE loading any show-specific config (episodes_registry, xiaoyuzhou.podcast_id, etc.). The existing Step 1 of the workflow currently reads `xiaoyuzhou.podcast_id` and `episodes_registry` at the top-level — this changes. Revised sequence:

1. Parse `--show` flag value (may be None).
2. Validate audio file exists.
3. Read sidecar manifest (if any). Extract `show:` field.
4. Resolve effective show via this precedence:
   - sidecar `show` + explicit `--show` match → use it.
   - sidecar `show` + explicit `--show` mismatch → **hard error** (`ShowMismatchError`). Print both; do not proceed.
   - sidecar `show` only → use sidecar's show.
   - explicit `--show` only (no sidecar or sidecar lacks `show:`) → use `--show`.
   - neither → apply `resolve_show_for_mutation(shows, None)`.
5. NOW load that show's `episodes_registry` path, `xiaoyuzhou.podcast_id`, etc. All subsequent steps (create staging dir, read registry, write registry) use the show's config.

Tests cover every branch of step 4, plus a regression test that kb-publish never reads `episodes_registry` before step 4 completes.

#### kb-notebooklm

- Podcast workflow reads show config on step 1 (preamble) by resolving the requested show. The host pool, intro music, **language**, and transcript settings all come from the show's own fields.
- Podcast `params_hash` includes `show.id` and `show.language` as inputs. Changing the show id or its generation language produces a distinct hash; dedup correctly distinguishes runs across shows or language changes.
- The `notebooklm generate audio --language <lang>` CLI argument receives `show.language` (not `integrations.notebooklm.language` which is removed by this spec).
- The rendered prompt's `{language}` placeholder (if any prompt template uses one for explicit language instruction) is substituted from `show.language`.
- Regression test: grep the entire plugin source tree for `integrations.notebooklm.language` — zero matches required.
- Step 4b (confidentiality filter) — unchanged.
- Step 5b (dedup judge) — when building `prior_hits`, scan only THIS show's `wiki/episodes/<show>/` directory. Concepts covered in other shows do NOT count against dedup; each show is its own series.
- Step 6a' (series-bible compilation) — include only THIS show's published episodes in the bible. **Series-bible header** (currently hardcoded `SERIES CONTINUITY — "全栈AI" Podcast`) renders from `show.title`: `SERIES CONTINUITY — "{show.title}" Podcast`.
- Step 6a'' — intro music probe uses the show's `intro_music` field.
- Step 6k (background agent) — assembled MP3 goes to `<output_path>/podcast-<show-id>-<theme>-YYYY-MM-DD.mp3` (filename stem gains show prefix to avoid collisions when a second show is introduced). **Transcription title** passed to `transcribe_audio.py` uses `show.title`: `"{show.title} — {theme} ({date})"`.
- `/kb-notebooklm podcast --show <id>` resolves the show; otherwise default.
- `/kb-notebooklm status` — accepts `--show <id>` (default: all shows).
- `/kb-notebooklm cleanup` — accepts `--show <id>` (default: all shows, per-show state still isolated).

**Branding touchpoints (all must render from `show.title`, never hardcoded):**

| File | Current hardcoded | After |
|---|---|---|
| `prompts/podcast-tutor.md` line 5 | `This is an episode of 全栈AI` | `This is an episode of {show_title}` — rendered into prompt from resolved show |
| `prompts/podcast-tutor.md` host intro (line ~28) | `欢迎收听全栈AI` | `欢迎收听{show_title}` |
| SKILL.md series-bible template | `SERIES CONTINUITY — "全栈AI" Podcast` | `SERIES CONTINUITY — "{show_title}" Podcast` |
| `kb-notebooklm/scripts/transcribe_audio.py` default title template | `全栈AI — <theme> (<date>)` | Script is updated: `--title` is **required** (no longer optional). Invoking without `--title` is an error. Removes the legacy `derive_title()` fallback that hardcoded `全栈AI`. Tests enforce the invariant by invoking without `--title` and expecting an error. |
| `kb-publish/prompts/cover-style.md` | `全栈AI` brand references | Templated to `{show_title}` |
| SKILL.md transcript default-filename derivation | `全栈AI — <stem>` fallback | Removed. `--title` is required on `transcribe_audio.py` invocations (see row above). The fallback logic and its `全栈AI` hardcoding are deleted entirely. |

**New prompt placeholder:** `{show_title}` and `{show_id}` become available to `podcast-tutor.md` alongside `{host0}`, `{host1}`, `{series_context}`, `{lesson_list}`. Rendered at step 6a'. Tests include an end-to-end check that no prompt file contains the literal string `全栈AI` — all brand text flows from config.

#### kb-init

- Fresh installs seed `integrations.shows[0]` with `default: true` and prompt for `id`, `title`, `description`, `hosts`. Other per-show fields fall back to sensible defaults (e.g., `transcript.model: large-v3`).
- Default `shows[0].id = "main"` if user doesn't pick one; the CLI still accepts `--show-id`.
- Existing kb-init integrations (xiaoyuzhou, gemini) write their config under the show entry when they need per-show values.

#### kb (the umbrella skill)

- New `/kb migrate` subcommand (section 7).
- The existing workflows (compile, query, lint, evolve) are NOT show-scoped. Wiki content is shared across shows.

### 8a. State file + sidecar manifest show-awareness

`.notebooklm-state.yaml` currently holds `runs[]`, `notebooks[]`, `last_podcast` cursor, etc. — all implicitly for "the" single show. Multi-show requires these to be scoped per show:

```yaml
# .notebooklm-state.yaml after migration
shows:
  quanzhan-ai:
    last_podcast: {mtime: "...", path: "..."}  # was top-level
    last_digest: null
    last_quiz: null
    notebooks: [...]                            # only this show's notebooks
    runs: [...]                                 # only this show's runs
```

All state mutations happen inside a specific show's scope. `/kb-notebooklm status` with no `--show` iterates all shows and prints each. `/kb-notebooklm cleanup --show <id>` scopes to that show's `runs[]` and `notebooks[]`.

The sidecar manifest (`<audio>.mp3.manifest.yaml`) gains a top-level `show: <id>` field, so `kb-publish` reading a sidecar knows which show's registry (`episodes_registry` path) to write into.

**State file migration ordering — dual-format reader:**

Naively rewriting `.notebooklm-state.yaml` before the `kb.yaml` commit would leave old kb-notebooklm code (still reading the old kb.yaml) encountering the new state schema → crash. Two options resolve this:

- **Option A (chosen):** Make the state-file LOADER dual-format. A top-level `last_podcast` field is read as the legacy default-show-scoped record. A top-level `shows:` field is read as multi-show. Writers always produce the new format. The loader lives in a shared helper (`state.py` or the relevant SKILL's inline code) that both formats can round-trip.
- Option B: Migrate the state file AFTER kb.yaml commit, as a separate atomic step.

Option A is simpler and safer: the state file migration becomes a lazy write-through — on first post-migration state mutation, it rewrites from legacy to new format. Explicit migration of the state file is still performed by `/kb migrate` for consistency, but the dual-format loader means ordering stops being a transaction risk.

**Migration steps for state file:**
- Read the existing `.notebooklm-state.yaml`.
- If already has `shows:` top-level: no-op.
- Else: wrap top-level keys (`last_podcast`, `last_digest`, `last_quiz`, `notebooks`, `runs`) under `shows.<default-show-id>.*`. Write to staging. Atomic replace as part of commit phase (sequence detailed below).
- Readers in kb-notebooklm and kb-publish detect the format by the presence of a `shows:` key at the top level; accept either.

**Sidecar manifests (`<audio>.mp3.manifest.yaml`):** Migrator scans BOTH `<output_path>/*.manifest.yaml` AND `<output_path>/notebooklm/*.manifest.yaml` (the legacy NotebookLM-downloads subdir). Anywhere the backfill CLI currently searches for audio (see `_resolve_audio_path` which checks both paths), the migrator also checks for sidecars. Each sidecar gets `show: <default-show-id>` added in-place (atomically, temp file + os.replace). If the audio has already been consumed by `kb-publish` (sidecar deleted), nothing to migrate. Future generation writes the field from the start.

**Legacy-location sidecar test fixture:** the migrator test suite includes a fixture with sidecars in both `output/` and `output/notebooklm/` locations and confirms both get migrated.

**Non-podcast workflows (quiz, digest, report, research-audio):** These ALSO become show-scoped in the new state file. All `runs[]` entries — podcast + quiz + digest + report + research-audio — live under `shows.<show-id>.runs[]`. Their CLI semantics follow the mutating resolver: `/kb-notebooklm quiz --show <id>` required when multiple shows exist, implicit single show otherwise. State migration moves every existing run (regardless of workflow) into `shows.<default-show-id>.runs[]`. Report, research-audio, etc. gain `--show` flags matching the pattern.

**Rule for generation parameters on non-podcast workflows:** After resolving the effective show (via `resolve_show_for_mutation`), every generation parameter that used to read from `integrations.notebooklm.*` (top-level) — especially `language`, and any value that participates in `params_hash` — reads from that `Show` instead. Concretely:

- `quiz`: `--language` comes from `show.language`, not `integrations.notebooklm.language`.
- `digest`: same.
- `report`: same for language; `--format` and `--topic` unaffected (those are command-level).
- `research-audio`: same for language.

Each workflow's `params_hash` input list gains `show.id` as a prefix and uses `show.language` in place of the legacy global. Existing pre-migration `runs[]` entries don't retroactively recompute — they carry their old hashes, which silently dedupe against old params; new runs hash under the new scheme.

The SKILL.md sections for these four workflows each get a single added bullet: "Read `show.language`, not `integrations.notebooklm.language`. The latter is removed by this spec." Leaving a code path that reads the removed global is a spec violation and must be caught by unit tests.

### 8b. Output scoping for every show-scoped workflow

The global `integrations.notebooklm.output_path` is shared across shows, but EVERY generated artifact gets a `<show-id>-` filename prefix to prevent collisions. This applies to ALL show-scoped workflows, not just podcast audio:

| Workflow | Old filename | New filename |
|---|---|---|
| `podcast` audio | `podcast-<theme>-YYYY-MM-DD.mp3` | `podcast-<show-id>-<theme>-YYYY-MM-DD.mp3` |
| `podcast` raw audio | `.raw.mp3` suffix on the above | same new prefix + `.raw.mp3` |
| `podcast` VTT / transcript | `<stem>.vtt` / `<stem>.transcript.md` | `<new-stem>.vtt` / `<new-stem>.transcript.md` |
| `podcast` sidecar manifest | `<stem>.mp3.manifest.yaml` | `<new-stem>.mp3.manifest.yaml` |
| `quiz` artifacts | `quiz-<theme>-YYYY-MM-DD.md` / `.json` / `flashcards-<theme>-*.md` | `quiz-<show-id>-<theme>-YYYY-MM-DD.md` etc. |
| `digest` audio | `digest-YYYY-MM-DD.mp3` | `digest-<show-id>-YYYY-MM-DD.mp3` |
| `report` artifacts | `report-<topic>-YYYY-MM-DD.md` | `report-<show-id>-<topic>-YYYY-MM-DD.md` |
| `research-audio` | `research-audio-YYYY-MM-DD.mp3` | `research-audio-<show-id>-YYYY-MM-DD.mp3` |

The show-prefix segment appears even in single-show deployments (no special case for "the one and only show"). Rationale: future shows don't require a rename, and `ls output/` tells you which show owns each file at a glance.

**Tests** (one per workflow): two shows (A and B) running the same workflow on the same day with the same theme produce distinct output files. Each show's `runs[].output_files[]` lists only its own files. The two runs' `params_hash` values differ because `show.id` is a hash input (§8a).

**Migration for old output files:** existing pre-migration files (like `podcast-quantization-2026-04-22.mp3`) do NOT get renamed. They remain as-is, referenced by their pre-migration `podcast_outputs` records in state. New files use the new prefix going forward.

**Legacy-path recovery rule (required for dedup/reprocess correctness):** when kb-notebooklm workflows (step 6c dedup, postproc recovery) look for an existing audio/transcript file for a matched run, the lookup order is:

1. If `podcast_outputs.raw_audio` / `.final_audio` / etc. fields are set in the matched `runs[]` record: use those paths as-is. They may be legacy pre-migration paths without `<show-id>-` prefix; that's fine — they existed before this spec.
2. Only when a field is null (or for brand-new runs): derive the new `<show-id>-<theme>-YYYY-MM-DD` stem.

This means: reprocessing EP3 v2 (generated before this spec ships) uses the stored `/Users/dragon/Documents/MLL/output/podcast-quantization-2026-04-22.raw.mp3` path from its `runs[]` record, not a newly-derived `podcast-quanzhan-ai-quantization-2026-04-22.raw.mp3`. A regression test with a fixture state containing a legacy run record confirms the workflow finds the retained raw and re-processes without regeneration.

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
| Multiple shows, mutating command, no `--show` | `AmbiguousShowError` with list of show ids and `--show` suggestion. Note: this fires regardless of any show being marked `default: true` — mutating resolver never consults the flag. |
| `--show <id>` doesn't match any show | `ShowNotFoundError` listing available ids. |
| Episode article has `prior_episode_ref: <int>` (legacy) | Post-migration runtime: **raise `MigrationRequiredError`** with a clear message pointing at `/kb migrate`. NO silent fallback — in a multi-show KB, guessing the show is provenance corruption. |
| Stub frontmatter has legacy string form | Same — raise `MigrationRequiredError`. Only the migrator accepts legacy forms. |
| Two stubs have the same slug but different shows created it | Not possible in practice (stubs are vault-wide; `referenced_by` list just accumulates refs from multiple shows). |
| A show config's `wiki_episodes_dir` points outside `wiki_path` | Validation error. |
| Migrator runs on partially-migrated KB (e.g., kb.yaml migrated but wiki/episodes/ not moved) | Detects by checking `wiki/episodes/*.md` existence at root-level; offers to "resume" migration. Atomic commit in the first run should prevent this, but surface cleanly if it happens. |

### 11. Testing

**Unit tests** (hermetic):

1. `shows.py`:
   - `validate_shows` accepts a valid single-show config; rejects missing `shows[]`, duplicate ids, bad id format, duplicate `episodes_registry`, duplicate `wiki_episodes_dir`, bad `wiki_episodes_dir` (outside `wiki_path`).
   - `resolve_show_for_mutation`: single show returns it; explicit id returns it; multi + None raises `AmbiguousShowError`; unknown id raises `ShowNotFoundError`. Default flag is irrelevant.
   - `resolve_show_for_read`: single show returns it; explicit id returns it; multi + None returns `None` (iterate-all signal); unknown id raises.
   - `EpRef.from_dict`: valid dict parses; extra keys ignored; missing show/ep raises; wrong type raises.
   - `EpRef.from_legacy`: str `ep-3` parses with default_show kwarg; bare int parses; non-matching str raises.
   - `parse_ep_ref_field`: legacy str/int raises `MigrationRequiredError`; unknown show in dict raises `UnknownShowError`; valid dict returns EpRef.
   - `EpRef.wikilink_stem(show, slug)` uses `show.wiki_episodes_dir`.
2. `episode_wiki.py` (updates):
   - `scan_episode_wiki` walks `wiki/episodes/<show>/*.md` subdirs; `strict=False` lenient skip on malformed files still works.
   - `compute_stub_update` produces dict-form `created_by`/`last_seen_by`/`best_depth_episode`/`referenced_by`.
   - `render_stub` emits dict-form frontmatter fields.
   - `render_episode_wiki`'s `index.concepts[].prior_episode_ref` is dict.
3. `migrate_multi_show.py`:
   - Detection tri-state: fully_migrated, unmigrated, partially_migrated all classify correctly.
   - `fully_migrated` exits idempotently.
   - `unmigrated`: full migration transforms a fixture KB correctly.
   - `partially_migrated` scenario 1 (crash before kb.yaml swap): simulated by running migration up through episode-article move, then halting before kb.yaml write. Rerun detects partial state, resumes from kb.yaml swap. Final state valid.
   - `partially_migrated` scenario 2 (crash after kb.yaml swap): simulated by running kb.yaml swap but halting before all stub updates commit. Rerun detects legacy stubs still present, finishes their migration. Final state valid.
   - Dry-run produces correct report without modifying anything.
   - Validation failure aborts without modifying anything.
   - Post-migration, `scan_episode_wiki` and `load_shows` both succeed on the output.
   - Post-migration, every `parse_ep_ref_field` call with `known_shows={"quanzhan-ai"}` succeeds.
   - An intentionally corrupted stub (legacy string `ep-1` that the migrator missed) is caught by post-commit validation.
   - Sidecar migration: fixture has sidecars in both `output/*.manifest.yaml` and `output/notebooklm/*.manifest.yaml`; both get `show:` added.
   - Stub body-prose wikilink: fixture has a stub with `Introduced in [[wiki/episodes/ep-1-...]]` in the body; migrator rewrites it to `[[wiki/episodes/<show>/ep-1-...]]`; post-validation `grep` for flat wikilinks returns zero matches.

4. Dual-format state file loader (`state.py` or inline in kb-notebooklm scripts):
   - `load_state(legacy-format YAML)` — reads top-level `last_podcast`/`last_digest`/`last_quiz`/`notebooks`/`runs`, returns a state object where those fields are keyed under `shows.<default-show-id>.*`.
   - `load_state(new-format YAML with shows: {...})` — reads directly into the state object.
   - `write_state(state) -> YAML` — always writes new format.
   - Round-trip: load legacy → write → load → state is preserved under the new shape.
   - Per-show isolation: a state with two shows updates `shows.A.last_podcast` without touching `shows.B.last_podcast`.
   - `/kb-notebooklm status --show A` surfaces only show A's state; `/kb-notebooklm status` (no `--show`) surfaces both.

5. Non-podcast workflow hashing and show-awareness (kb-notebooklm):
   - `quiz`, `digest`, `report`, `research-audio` each have a test that:
     - `params_hash` changes when `show.id` changes (two shows with same other params yield distinct hashes).
     - `params_hash` changes when `show.language` changes.
     - No call site reads `integrations.notebooklm.language` — the removed global — verified by grep across the plugin source tree.
     - With `--show` omitted in a multi-show KB, the command raises `AmbiguousShowError` before any NotebookLM API call.
   - Cross-show dedup scope: two-show fixture where both shows cover the same concept. `concepts_covered_by_episodes` called after `scan_episode_wiki(show=show_A)` returns ONLY show_A's hits for that concept. Dedup judge's `prior_hits` contains only show_A's entries.
   - Shared params-hash helper (if one is extracted) receives `show.id` as a required input; tests cover that changing show changes the hash.

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
