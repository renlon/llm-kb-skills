"""Multi-show podcast support: Show dataclass, EpRef value object,
resolvers, validators.

See docs/superpowers/specs/2026-04-23-multi-show-podcast-support-design.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ID_PATTERN = re.compile(r"^[a-z][a-z0-9\-]{0,31}$")


class ShowConfigError(ValueError):
    """Raised on any show-config validation failure."""


class ShowNotFoundError(ShowConfigError):
    """Requested show id is not configured."""


class AmbiguousShowError(ShowConfigError):
    """Multi-show KB without --show flag on a mutating command."""


class UnknownShowError(ShowConfigError):
    """EpRef.show not in known_shows set."""


class ShowMismatchError(ShowConfigError):
    """Sidecar manifest `show:` conflicts with the --show flag or resolved show."""


class MigrationRequiredError(RuntimeError):
    """Legacy str/int episode ref encountered at runtime — /kb migrate is required."""


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
    transcript: dict          # {enabled, model, device, language}
    episodes_registry: str    # project-root-relative
    wiki_episodes_dir: str    # wiki-root-relative, always equals "episodes/{id}"
    xiaoyuzhou: dict          # {podcast_id: str | None}

    def __post_init__(self):
        # Enforce the wiki_episodes_dir invariant at construction time.
        expected = f"episodes/{self.id}"
        if self.wiki_episodes_dir != expected:
            raise ShowConfigError(
                f"show {self.id!r}: wiki_episodes_dir must equal {expected!r}, "
                f"got {self.wiki_episodes_dir!r}"
            )


def validate_shows(
    shows_raw: list[dict],
    *,
    project_root: Path,
    wiki_path: Path,
) -> list[Show]:
    """Validate raw show dicts from kb.yaml; return typed Show objects.

    Raises ShowConfigError on any violation. Reports ALL violations at once
    (not first-failure-only).

    `project_root` and `wiki_path` are accepted but not yet consulted — they
    are reserved for forthcoming cross-reference checks (e.g. verifying that
    `wiki_path / show.wiki_episodes_dir` is resolvable, or that
    `project_root / show.episodes_registry` does not collide with external
    sources). Callers should always pass real values so the API is stable
    when those checks land.
    """
    errors: list[str] = []

    if not isinstance(shows_raw, list) or not shows_raw:
        raise ShowConfigError("integrations.shows must be a non-empty list (at least one)")

    seen_ids: set[str] = set()
    seen_registries: set[str] = set()
    seen_wiki_dirs: set[str] = set()
    seen_podcast_ids: set[str] = set()
    shows: list[Show] = []

    defaults_count = 0

    for i, raw in enumerate(shows_raw):
        if not isinstance(raw, dict):
            errors.append(f"shows[{i}] is not a dict")
            continue

        show_id = raw.get("id")
        if not isinstance(show_id, str) or not _ID_PATTERN.match(show_id):
            errors.append(f"shows[{i}].id={show_id!r} must match pattern {_ID_PATTERN.pattern}")
            continue

        if show_id in seen_ids:
            errors.append(f"duplicate show id {show_id!r}")
            continue
        seen_ids.add(show_id)

        if raw.get("default") is True:
            defaults_count += 1

        # wiki_episodes_dir: must equal episodes/<id>
        wed = raw.get("wiki_episodes_dir", f"episodes/{show_id}")
        expected_wed = f"episodes/{show_id}"
        if wed != expected_wed:
            errors.append(
                f"shows[{i}].wiki_episodes_dir={wed!r} must equal {expected_wed!r}"
            )
            continue

        # Uniqueness checks
        registry = raw.get("episodes_registry", "episodes.yaml")
        if registry in seen_registries:
            errors.append(f"episodes_registry {registry!r} duplicate across shows")
            continue
        seen_registries.add(registry)

        if wed in seen_wiki_dirs:
            errors.append(f"wiki_episodes_dir {wed!r} duplicate across shows")
            continue
        seen_wiki_dirs.add(wed)

        xiaoyu = raw.get("xiaoyuzhou") or {}
        pod_id = xiaoyu.get("podcast_id")
        if pod_id:
            if pod_id in seen_podcast_ids:
                errors.append(f"xiaoyuzhou.podcast_id {pod_id!r} duplicate across shows")
                continue
            seen_podcast_ids.add(pod_id)

        try:
            show = Show(
                id=show_id,
                title=str(raw.get("title", "")),
                description=str(raw.get("description", "")),
                default=bool(raw.get("default", False)),
                language=str(raw.get("language", "en")),
                hosts=list(raw.get("hosts") or []),
                extra_host_names=list(raw.get("extra_host_names") or []),
                intro_music=raw.get("intro_music"),
                intro_music_length_seconds=float(raw.get("intro_music_length_seconds", 12)),
                intro_crossfade_seconds=float(raw.get("intro_crossfade_seconds", 3)),
                podcast_format=str(raw.get("podcast_format", "deep-dive")),
                podcast_length=str(raw.get("podcast_length", "long")),
                transcript=dict(raw.get("transcript") or {}),
                episodes_registry=registry,
                wiki_episodes_dir=wed,
                xiaoyuzhou=dict(xiaoyu),
            )
            shows.append(show)
        except Exception as e:
            errors.append(f"shows[{i}] construction failed: {e}")

    if defaults_count > 1:
        errors.append(f"only one show may be marked default; found {defaults_count}")

    if errors:
        raise ShowConfigError("\n".join(errors))

    return shows


def load_shows(kb_yaml: dict, project_root: Path) -> list[Show]:
    """Load and validate `integrations.shows[]` from parsed kb.yaml.

    Reads `integrations.notebooklm.wiki_path` for the wiki root.
    """
    integrations = kb_yaml.get("integrations") or {}
    notebooklm = integrations.get("notebooklm") or {}
    wiki_path_str = notebooklm.get("wiki_path")
    if not wiki_path_str:
        raise ShowConfigError(
            "integrations.notebooklm.wiki_path is required but missing"
        )
    wiki_path = Path(wiki_path_str)
    shows_raw = integrations.get("shows")
    if shows_raw is None:
        raise ShowConfigError(
            "integrations.shows is missing — run `/kb migrate` to convert a single-show KB"
        )
    return validate_shows(shows_raw, project_root=project_root, wiki_path=wiki_path)
