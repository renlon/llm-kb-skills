"""Shared pytest fixtures for kb/scripts/migrate_multi_show tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Allow direct imports from the local kb/scripts/ dir.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also allow imports from the sibling kb-publish/scripts/ dir — the migrator
# reuses shows.py, state.py, lock.py, and episode_wiki.py from there.
_SIBLING_SCRIPTS = (
    Path(__file__).resolve().parents[3] / "kb-publish" / "scripts"
)
if str(_SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SIBLING_SCRIPTS))


@pytest.fixture
def pre_migration_kb(tmp_path: Path) -> Path:
    """Build a minimal pre-migration KB fixture: kb.yaml + .notebooklm-state.yaml + wiki/episodes/flat + stubs."""
    project = tmp_path / "project"
    project.mkdir()
    wiki = project / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    (wiki / "attention").mkdir()
    output = project / "output"
    output.mkdir()

    # Legacy kb.yaml (single-show)
    (project / "kb.yaml").write_text(
        "integrations:\n"
        "  notebooklm:\n"
        "    enabled: true\n"
        "    cli_path: /dev/null\n"
        "    venv_path: /dev/null\n"
        "    lessons_path: " + str(project / "lessons") + "\n"
        "    wiki_path: " + str(wiki) + "\n"
        "    output_path: " + str(output) + "\n"
        "    language: zh_Hans\n"
        "    podcast:\n"
        "      format: deep-dive\n"
        "      length: long\n"
        "      hosts: ['A', 'B']\n"
        "      intro_music: /dev/null/intro.mp3\n"
        "      intro_music_length_seconds: 12\n"
        "      intro_crossfade_seconds: 3\n"
        "      transcript:\n"
        "        enabled: false\n"
        "        model: large-v3\n"
        "        device: auto\n"
        "        language: zh\n"
        "  xiaoyuzhou:\n"
        "    enabled: true\n"
        "    podcast_id: 'LEGACY_PODCAST_ID'\n"
        "    episodes_registry: episodes.yaml\n"
        "    browser_data: .browser-data\n"
        "    staging_dir: output/staging\n"
        "    venv_path: /dev/null\n",
        encoding="utf-8",
    )

    # Legacy episodes.yaml
    (project / "episodes.yaml").write_text(
        "episodes:\n"
        "  - id: 1\n"
        "    title: 'EP1 | Test'\n"
        "    topic: Test\n"
        "    date: '2026-04-01'\n"
        "    status: published\n"
        "    audio: podcast-test-2026-04-01.mp3\n"
        "next_id: 2\n",
        encoding="utf-8",
    )

    # Legacy state file
    (project / ".notebooklm-state.yaml").write_text(
        "last_podcast: null\n"
        "last_digest: null\n"
        "last_quiz: null\n"
        "notebooks: []\n"
        "runs: []\n",
        encoding="utf-8",
    )

    # One flat episode article at legacy path
    (wiki / "episodes" / "ep-1-test.md").write_text(
        "---\n"
        "title: 'EP1 | Test'\n"
        "episode_id: 1\n"
        "audio_file: podcast-test-2026-04-01.mp3\n"
        "transcript_file: podcast-test-2026-04-01.transcript.md\n"
        "date: '2026-04-01'\n"
        "depth: intro\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/attention/self-attention\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: new\n"
        "      prior_episode_ref: null\n"
        "      what: 'W'\n"
        "      why_it_matters: 'Y'\n"
        "      key_points: ['k']\n"
        "      covered_at_sec: 1.0\n"
        "      existed_before: false\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n"
        "\n"
        "# EP1 | Test\n"
        "\n"
        "See [[wiki/episodes/ep-1-test]] for details.\n",
        encoding="utf-8",
    )

    # One legacy stub
    (wiki / "attention" / "self-attention.md").write_text(
        "---\n"
        "title: Self Attention\n"
        "tags: [stub, attention]\n"
        "aliases: []\n"
        "status: stub\n"
        "created_by: ep-1\n"
        "last_seen_by: ep-1\n"
        "best_depth_episode: ep-1\n"
        "best_depth: explained\n"
        "referenced_by: [ep-1]\n"
        "created: '2026-04-01'\n"
        "---\n"
        "\n"
        "# Self Attention\n"
        "\n"
        "Stub. Introduced in [[wiki/episodes/ep-1-test]].\n",
        encoding="utf-8",
    )

    return project


@pytest.fixture
def realistic_pre_migration_kb(tmp_path: Path) -> Path:
    """Build a KB fixture with 2 episodes, multiple stubs, body wikilinks
    everywhere, a non-episode wiki note, legacy state file, sidecars in
    both locations."""
    project = tmp_path / "project"
    project.mkdir()
    wiki = project / "wiki"
    for sub in ("episodes", "attention", "quantization", "notes"):
        (wiki / sub).mkdir(parents=True)
    output = project / "output"
    (output / "notebooklm").mkdir(parents=True)
    (project / "lessons").mkdir()

    # kb.yaml
    (project / "kb.yaml").write_text(yaml.safe_dump({
        "integrations": {
            "notebooklm": {
                "enabled": True,
                "cli_path": "/dev/null",
                "venv_path": "/dev/null",
                "lessons_path": str(project / "lessons"),
                "wiki_path": str(wiki),
                "output_path": str(output),
                "language": "zh_Hans",
                "podcast": {
                    "format": "deep-dive",
                    "length": "long",
                    "hosts": ["A", "B"],
                    "intro_music": "/dev/null/intro.mp3",
                    "intro_music_length_seconds": 12,
                    "intro_crossfade_seconds": 3,
                    "transcript": {"enabled": False, "model": "large-v3",
                                   "device": "auto", "language": "zh"},
                },
            },
            "xiaoyuzhou": {
                "enabled": True,
                "podcast_id": "LEGACY",
                "episodes_registry": "episodes.yaml",
                "browser_data": ".browser-data",
                "staging_dir": "output/staging",
                "venv_path": "/dev/null",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    # episodes.yaml
    (project / "episodes.yaml").write_text(yaml.safe_dump({
        "episodes": [
            {"id": 1, "title": "EP1 | Intro", "topic": "Intro",
             "date": "2026-04-01", "status": "published",
             "audio": "podcast-intro-2026-04-01.mp3"},
            {"id": 2, "title": "EP2 | Deep Dive", "topic": "Deep Dive",
             "date": "2026-04-10", "status": "published",
             "audio": "podcast-deep-dive-2026-04-10.mp3"},
        ],
        "next_id": 3,
    }), encoding="utf-8")

    # Legacy state file
    (project / ".notebooklm-state.yaml").write_text(yaml.safe_dump({
        "last_podcast": None,
        "last_digest": None,
        "last_quiz": None,
        "notebooks": [],
        "runs": [],
    }), encoding="utf-8")

    # Episode articles
    def _episode_md(ep_id: int, slug: str, title: str, builds_on: list) -> str:
        index = {
            "schema_version": 1,
            "summary": f"Summary for ep {ep_id}.",
            "concepts": [
                {
                    "slug": "wiki/attention/self-attention",
                    "depth_this_episode": "explained",
                    "depth_delta_vs_past": "new",
                    "prior_episode_ref": None,
                    "what": "W", "why_it_matters": "Y",
                    "key_points": ["k"], "covered_at_sec": 1.0,
                    "existed_before": False,
                },
            ],
            "open_threads": [],
            "series_links": {"builds_on": builds_on, "followup_candidates": []},
        }
        fm = {
            "title": title,
            "episode_id": ep_id,
            "audio_file": f"podcast-{slug}-2026-04-01.mp3",
            "transcript_file": f"podcast-{slug}-2026-04-01.transcript.md",
            "date": "2026-04-01",
            "depth": "intro",
            "tags": ["episode"],
            "aliases": [],
            "source_lessons": [],
            "index": index,
        }
        body = (
            f"\n# {title}\n\n"
            f"See [[wiki/episodes/ep-{ep_id}-{slug}]] for details. "
            f"Also related: [[wiki/episodes/ep-1-intro|the first episode]].\n"
        )
        return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n" + body

    (wiki / "episodes" / "ep-1-intro.md").write_text(
        _episode_md(1, "intro", "EP1 | Intro", []), encoding="utf-8")
    (wiki / "episodes" / "ep-2-deep-dive.md").write_text(
        _episode_md(2, "deep-dive", "EP2 | Deep Dive", [1]), encoding="utf-8")

    # Stubs — legacy ep-N str/int form in frontmatter
    (wiki / "attention" / "self-attention.md").write_text(
        "---\n"
        "title: Self Attention\ntags: [stub]\naliases: []\nstatus: stub\n"
        "created_by: ep-1\nlast_seen_by: ep-2\nbest_depth_episode: ep-2\n"
        "best_depth: explained\nreferenced_by: [ep-1, ep-2]\n"
        "created: '2026-04-01'\n---\n\n"
        "# Self Attention\n\nStub. See [[wiki/episodes/ep-1-intro]].\n",
        encoding="utf-8")
    (wiki / "quantization" / "int8.md").write_text(
        "---\n"
        "title: INT8 Quantization\ntags: [stub]\naliases: []\nstatus: stub\n"
        "created_by: ep-2\nlast_seen_by: ep-2\nbest_depth_episode: ep-2\n"
        "best_depth: explained\nreferenced_by: [ep-2]\n"
        "created: '2026-04-10'\n---\n\n"
        "# INT8 Quantization\n\nStub. [[wiki/episodes/ep-2-deep-dive|deep dive]].\n",
        encoding="utf-8")

    # Non-episode wiki note with legacy body wikilink
    (wiki / "notes" / "reading-list.md").write_text(
        "# Reading List\n\n"
        "- [[wiki/episodes/ep-1-intro|EP1]]\n"
        "- [[wiki/episodes/ep-2-deep-dive]]\n",
        encoding="utf-8")

    # Sidecar manifests (both locations, neither has show: yet)
    (output / "podcast-intro-2026-04-01.mp3.manifest.yaml").write_text(
        yaml.safe_dump({
            "episode_id": 1, "audio": "podcast-intro-2026-04-01.mp3",
            "date": "2026-04-01", "title": "EP1 | Intro",
        }), encoding="utf-8")
    (output / "notebooklm" / "podcast-intro-2026-04-01.notebooklm.manifest.yaml").write_text(
        yaml.safe_dump({
            "episode_id": 1, "notebook_id": "nb-123",
            "source_lessons": [], "generated_at": "2026-04-01",
        }), encoding="utf-8")

    return project
