#!/usr/bin/env python3
"""Backfill the episode index for already-published episodes.

Reads kb.yaml + episodes.yaml, iterates published episodes, transcribes any
missing transcripts using plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py,
then calls orchestrate_episode_index to produce wiki/episodes/ records.

Also used at publish time by kb-publish step 8c (imports and calls the same
orchestration helper directly).

Exit codes:
  0  all requested episodes processed (some may have logged warnings / skips)
  1  unrecoverable error (missing config, unreadable files)
  2  invalid CLI arguments
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml


_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import episode_wiki as E  # noqa: E402


log = logging.getLogger("backfill_index")


def _load_kb_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_episodes_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"episodes": [], "next_id": 1}


def _atomic_write_yaml(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=".tmp-", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp = f.name
    os.replace(tmp, path)


def _resolve_audio_path(output_path: Path, audio_basename: str) -> Path | None:
    """Check <output_path>/<audio> then <output_path>/notebooklm/<audio>."""
    for candidate in (output_path / audio_basename,
                      output_path / "notebooklm" / audio_basename):
        if candidate.is_file():
            return candidate
    return None


def _transcript_exists(registry_entry: dict, audio_dir: Path) -> tuple[Path | None, Path | None]:
    """Return (transcript_md_path, vtt_path) if a transcript exists; else (None, None).
    Checks the registry's transcript.markdown first, then sibling-of-audio convention.
    """
    transcript_info = registry_entry.get("transcript") or {}
    md_name = transcript_info.get("markdown")
    vtt_name = transcript_info.get("vtt")
    if md_name:
        md_path = audio_dir / md_name
        if md_path.is_file():
            vtt_path = audio_dir / vtt_name if vtt_name else None
            return md_path, vtt_path

    # Sibling convention: <stem>.transcript.md
    audio_stem = Path(registry_entry["audio"]).stem
    sibling_md = audio_dir / f"{audio_stem}.transcript.md"
    sibling_vtt = audio_dir / f"{audio_stem}.vtt"
    if sibling_md.is_file():
        return sibling_md, sibling_vtt if sibling_vtt.is_file() else None
    return None, None


def _run_transcribe_subprocess(
    *,
    notebooklm_venv: Path,
    notebooklm_skill_dir: Path,
    audio_path: Path,
    output_vtt: Path,
    output_md: Path,
    host_pool: list[str],
    model: str,
    device: str,
    language: str,
    title: str,
) -> dict[str, Any]:
    """Invoke transcribe_audio.py as a subprocess. Returns the parsed JSON output."""
    script = notebooklm_skill_dir / "scripts" / "transcribe_audio.py"
    python_bin = notebooklm_venv / "bin" / "python3"
    cmd = [
        str(python_bin), str(script),
        "--audio", str(audio_path),
        "--hosts", json.dumps(host_pool, ensure_ascii=False),
        "--output-vtt", str(output_vtt),
        "--output-md", str(output_md),
        "--vtt-offset-seconds", "0",
        "--model", model,
        "--device", device,
        "--language", language,
        "--title", title,
        "--json",
    ]
    log.info("Transcribing %s ...", audio_path.name)
    env = os.environ.copy()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"transcribe_audio.py exited {result.returncode}: {result.stderr.strip()[:500]}"
        )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"transcribe_audio.py stdout was not JSON: {e}") from e


def _make_haiku_call(model: str | None = None) -> Callable[[str], str]:
    """Build a Haiku caller, auto-detecting Bedrock vs direct Anthropic API.

    Bedrock path (when CLAUDE_CODE_USE_BEDROCK=1 or AWS_REGION is set):
      uses anthropic.AnthropicBedrock; model IDs follow Bedrock naming
      (from ANTHROPIC_DEFAULT_HAIKU_MODEL if set).

    Direct API path: uses anthropic.Anthropic with ANTHROPIC_API_KEY.
    """
    use_bedrock = os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1" or bool(os.environ.get("AWS_REGION"))
    if model is None:
        if use_bedrock:
            model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
        else:
            model = "claude-haiku-4-5-20251001"

    if use_bedrock:
        try:
            from anthropic import AnthropicBedrock
        except ImportError as e:
            raise RuntimeError(
                "The 'anthropic' package with Bedrock support is required. "
                "Install with: pip install 'anthropic[bedrock]'"
            ) from e
        client = AnthropicBedrock()
    else:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(
                "The 'anthropic' package is required. "
                "Install with: pip install anthropic"
            ) from e
        client = Anthropic()

    def _call(prompt: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=32000,  # Large enough for 15-40 concepts × multi-line key_points
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    return _call


def _update_registry_for_episode(
    registry: dict,
    episode_id: int,
    extraction: dict,
    transcript_vtt: Path | None,
    transcript_md: Path,
) -> None:
    """Update the matching episodes[] entry with concepts_covered + open_threads + transcript info.

    Modifies `registry` in-place. Does NOT touch id/title/description/date/status.
    """
    for ep in registry.get("episodes", []) or []:
        if ep.get("id") == episode_id:
            ep["concepts_covered"] = [
                {"name": c["slug"].split("/")[-1], "depth": c["depth_this_episode"]}
                for c in extraction.get("concepts", []) or []
            ]
            ep["open_threads"] = [
                t.get("note") for t in extraction.get("open_threads", []) or [] if t.get("note")
            ]
            # Patch transcript block if we ran a fresh transcription.
            if transcript_md is not None:
                tr = ep.get("transcript") or {}
                tr["applied"] = True
                tr["markdown"] = transcript_md.name
                if transcript_vtt is not None:
                    tr["vtt"] = transcript_vtt.name
                ep["transcript"] = tr
            return
    raise RuntimeError(f"Episode id={episode_id} not found in registry")


def backfill_episode(
    *,
    ep_entry: dict,
    kb_config: dict,
    wiki_dir: Path,
    output_path: Path,
    notebooklm_venv: Path,
    notebooklm_skill_dir: Path,
    prompt_template_path: Path,
    haiku_call: Callable[[str], str],
) -> dict[str, Any]:
    """Backfill index for one episode. Returns a dict with stats for progress logging."""
    ep_id = ep_entry["id"]
    audio_basename = ep_entry["audio"]
    audio_path = _resolve_audio_path(output_path, audio_basename)
    if audio_path is None:
        raise FileNotFoundError(f"Audio not found: {audio_basename}")
    audio_dir = audio_path.parent

    transcript_md, transcript_vtt = _transcript_exists(ep_entry, audio_dir)
    transcribed = False
    if transcript_md is None:
        # Run transcription
        host_pool = (kb_config.get("integrations", {})
                     .get("notebooklm", {})
                     .get("podcast", {})
                     .get("hosts", ["瓜瓜龙", "海发菜"]))
        extra = (kb_config.get("integrations", {})
                 .get("notebooklm", {})
                 .get("podcast", {})
                 .get("extra_host_names", []))
        full_pool = list(host_pool) + list(extra)
        tr_cfg = (kb_config.get("integrations", {})
                  .get("notebooklm", {})
                  .get("podcast", {})
                  .get("transcript", {}))
        stem = Path(audio_basename).stem
        md_out = audio_dir / f"{stem}.transcript.md"
        vtt_out = audio_dir / f"{stem}.vtt"
        title = f"全栈AI — {ep_entry.get('topic', '')} ({ep_entry.get('date', '')})"
        _run_transcribe_subprocess(
            notebooklm_venv=notebooklm_venv,
            notebooklm_skill_dir=notebooklm_skill_dir,
            audio_path=audio_path,
            output_vtt=vtt_out,
            output_md=md_out,
            host_pool=full_pool,
            model=tr_cfg.get("model", "large-v3"),
            device=tr_cfg.get("device", "auto"),
            language=tr_cfg.get("language", "zh"),
            title=title,
        )
        transcript_md = md_out
        transcript_vtt = vtt_out
        transcribed = True

    # Call orchestrate
    tags = ["episode"]
    if ep_entry.get("topic"):
        tags.append(ep_entry["topic"].split()[0].lower())
    aliases = [f"EP{ep_id}"]
    result = E.orchestrate_episode_index(
        wiki_dir=wiki_dir,
        episode_id=ep_id,
        episode_topic=ep_entry.get("topic", "Untitled"),
        episode_date=str(ep_entry.get("date", "")),
        episode_depth=ep_entry.get("depth", "explained"),
        audio_file=audio_basename,
        transcript_path=transcript_md,
        transcript_file=transcript_md.name,
        tags=tags,
        aliases=aliases,
        source_lessons=list(ep_entry.get("source_lessons", []) or []),
        haiku_call=haiku_call,
        prompt_template_path=prompt_template_path,
    )
    return {
        "ep_id": ep_id,
        "transcribed": transcribed,
        "episode_article": str(result.episode_article),
        "new_stubs": len(result.new_stubs_created),
        "stubs_updated": len(result.stubs_updated),
        "collisions_skipped": len(result.collisions_skipped),
        "transcript_md": transcript_md,
        "transcript_vtt": transcript_vtt,
        "extraction": result,  # NOTE: TransactionalIndexResult, not raw extraction
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backfill episode index for published episodes.")
    parser.add_argument("--kb-yaml", default="kb.yaml", help="Path to kb.yaml (default: ./kb.yaml)")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--episode", type=int, help="Backfill one specific episode by id")
    grp.add_argument("--all", action="store_true", help="Backfill all published episodes")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    kb_path = Path(args.kb_yaml).resolve()
    if not kb_path.is_file():
        log.error("kb.yaml not found at %s", kb_path)
        return 1
    kb_config = _load_kb_yaml(kb_path)

    nb = kb_config.get("integrations", {}).get("notebooklm", {})
    xy = kb_config.get("integrations", {}).get("xiaoyuzhou", {})
    if not nb.get("enabled"):
        log.error("integrations.notebooklm.enabled is not true in kb.yaml")
        return 1
    wiki_dir = Path(nb["wiki_path"])
    output_path = Path(nb["output_path"])
    notebooklm_venv = Path(nb["venv_path"])
    # Skill dir: venv path is typically <vault>/../notebooklm-py/.venv; the kb-notebooklm
    # skill dir is the installed plugin's cached path. We resolve by locating transcribe_audio.py
    # relative to this script's own plugin tree.
    this_plugin_root = _SCRIPTS_DIR.parent.parent.parent  # plugins/kb/
    notebooklm_skill_dir = this_plugin_root / "skills" / "kb-notebooklm"
    if not (notebooklm_skill_dir / "scripts" / "transcribe_audio.py").is_file():
        log.error("Cannot find transcribe_audio.py at %s", notebooklm_skill_dir)
        return 1

    prompt_template_path = _SCRIPTS_DIR.parent / "prompts" / "episode-wiki-extract.md"
    if not prompt_template_path.is_file():
        log.error("Extract prompt template not found at %s", prompt_template_path)
        return 1

    registry_path = Path(xy.get("episodes_registry", "episodes.yaml"))
    if not registry_path.is_absolute():
        registry_path = kb_path.parent / registry_path
    if not registry_path.is_file():
        log.error("episodes.yaml not found at %s", registry_path)
        return 1
    registry = _load_episodes_yaml(registry_path)

    # Select episodes to backfill
    published = [e for e in (registry.get("episodes") or []) if e.get("status") == "published"]
    if args.episode is not None:
        targets = [e for e in published if e.get("id") == args.episode]
        if not targets:
            log.error("No published episode with id=%d found", args.episode)
            return 1
    else:
        targets = sorted(published, key=lambda e: e.get("id", 0))

    if not targets:
        log.info("No published episodes to backfill.")
        return 0

    haiku_call = _make_haiku_call()
    ok, failed = 0, 0
    for ep in targets:
        try:
            stats = backfill_episode(
                ep_entry=ep,
                kb_config=kb_config,
                wiki_dir=wiki_dir,
                output_path=output_path,
                notebooklm_venv=notebooklm_venv,
                notebooklm_skill_dir=notebooklm_skill_dir,
                prompt_template_path=prompt_template_path,
                haiku_call=haiku_call,
            )
            # Update registry
            # Re-derive extraction for registry update: re-open the just-written article? Cheaper:
            # reconstruct from the TransactionalIndexResult? We wrote the full index; re-read instead.
            ep_article = Path(stats["episode_article"])
            # Parse back to find concepts/open_threads for the registry
            text = ep_article.read_text(encoding="utf-8")
            fm_end = text.find("\n---\n", 4)
            fm = yaml.safe_load(text[4:fm_end])
            idx = fm.get("index", {})
            extraction_for_registry = {
                "concepts": idx.get("concepts", []),
                "open_threads": idx.get("open_threads", []),
            }
            _update_registry_for_episode(
                registry, ep["id"], extraction_for_registry,
                stats.get("transcript_vtt"), stats["transcript_md"],
            )
            _atomic_write_yaml(registry_path, registry)

            log.info(
                "EP%d: indexed (transcribed=%s, new_stubs=%d, stubs_updated=%d, collisions_skipped=%d). Article: %s",
                ep["id"], stats["transcribed"], stats["new_stubs"], stats["stubs_updated"],
                stats["collisions_skipped"], stats["episode_article"],
            )
            ok += 1
        except Exception as e:
            log.exception("EP%s backfill failed: %s", ep.get("id"), e)
            failed += 1
            continue

    log.info("Backfill complete: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
