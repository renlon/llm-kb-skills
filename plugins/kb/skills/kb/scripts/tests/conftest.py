"""Shared pytest fixtures for kb/scripts/migrate_multi_show tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
