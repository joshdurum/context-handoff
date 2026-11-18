#!/usr/bin/env python3
"""Create, validate (<400 words), and archive compact HANDOFF.md session briefs."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _common import estimate_tokens, git_short_status, word_count  # noqa: E402

MAX_HANDOFF_WORDS = 400
REQUIRED_HEADINGS = [
    "## Goal",
    "## Verified Done",
    "## Dead Ends (Do Not Retry)",
    "## Active Files",
    "## Next Exact Action",
]


def _extract_sections(markdown_text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped in REQUIRED_HEADINGS:
            current = stripped
            sections[current] = []
        elif stripped.startswith("## "):
            current = None
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def validate_handoff(markdown_text: str, max_words: int = MAX_HANDOFF_WORDS) -> dict[str, Any]:
    """Check strict 5-section schema and word budget on HANDOFF.md text."""
    words = word_count(markdown_text)
    tokens = estimate_tokens(markdown_text)
    sections = _extract_sections(markdown_text)

    errors: list[str] = []
    if words > max_words:
        errors.append(f"Word count {words} exceeds limit of {max_words} words.")
    for heading in REQUIRED_HEADINGS:
        if heading not in sections:
            errors.append(f"Missing required heading: {heading}")
        elif not sections[heading]:
            errors.append(f"Empty section under {heading}")

    return {
        "valid": len(errors) == 0,
        "words": words,
        "max_words": max_words,
        "est_tokens": tokens,
        "errors": errors,
    }


def archive_existing_handoff(project_dir: Path) -> Path | None:
    """Move an existing HANDOFF.md into .handoffs/archive/ with a UTC timestamp."""
    handoff_path = project_dir / "HANDOFF.md"
    if not handoff_path.is_file():
        return None
    archive_dir = project_dir / ".handoffs" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = archive_dir / f"{stamp}_HANDOFF.md"
    counter = 1
    while dest.exists():
        dest = archive_dir / f"{stamp}_{counter}_HANDOFF.md"
        counter += 1
    shutil.move(str(handoff_path), str(dest))
    return dest


def _format_bullets(items: list[str], fallback: str) -> str:
    cleaned = [re.sub(r"^\s*[-*]\s*", "", item.strip()) for item in items if item and item.strip()]
    if not cleaned:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in cleaned[:8])


def render_handoff(
    goal: str,
    done: list[str],
    dead_ends: list[str],
    active_files: list[str],
    next_action: str,
    git_lines: list[str] | None = None,
) -> str:
    """Render a compact 5-section HANDOFF.md within the 400-word budget."""
    files_list = list(active_files)
    if not files_list and git_lines:
        files_list = [f"`{line[3:].strip()}` (git: `{line[:2].strip() or 'M'}`)" for line in git_lines[:8]]

    text = "\n".join([
        "# Session Handoff",
        "",
        "## Goal",
        goal.strip() or "Continue project execution cleanly.",
        "",
        "## Verified Done",
        _format_bullets(done, "None verified yet."),
        "",
        "## Dead Ends (Do Not Retry)",
        _format_bullets(dead_ends, "None yet."),
        "",
        "## Active Files",
        _format_bullets(files_list, "Check `git status --short` or workspace root."),
        "",
        "## Next Exact Action",
        next_action.strip() or "Inspect workspace and execute next pending task.",
        "",
    ])
    return text


def build_boot_prompt(project_dir: Path) -> str:
    """Generate a compact 3-line prompt for pasting into a brand-new chat."""
    has_agents = (project_dir / "AGENTS.md").is_file()
    agents_note = "Read `AGENTS.md` and `HANDOFF.md`." if has_agents else "Read `HANDOFF.md`."
    return (
        f"{agents_note} Do not repeat anything listed under Dead Ends.\n"
        "First verify ground truth (`git status --short` if git exists and run tests if present).\n"
        "Then execute the Next Exact Action in `HANDOFF.md`."
    )


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS clipboard via pbcopy if available."""
    if not shutil.which("pbcopy"):
        return False
    proc = subprocess.run(["pbcopy"], input=text, text=True, capture_output=True, timeout=5)
    return proc.returncode == 0


def write_handoff(
    project_dir: Path,
    goal: str,
    done: list[str],
    dead_ends: list[str],
    active_files: list[str],
    next_action: str,
    archive_old: bool = True,
) -> dict[str, Any]:
    """Archive any prior handoff, write a validated HANDOFF.md, and build boot prompt."""
    archived = archive_existing_handoff(project_dir) if archive_old else None
    git_lines = git_short_status(project_dir)
    content = render_handoff(
        goal=goal,
        done=done,
        dead_ends=dead_ends,
        active_files=active_files,
        next_action=next_action,
        git_lines=git_lines,
    )
    validation = validate_handoff(content)
    if not validation["valid"]:
        raise ValueError(f"Generated HANDOFF.md failed validation: {validation['errors']}")

    handoff_path = project_dir / "HANDOFF.md"
    handoff_path.write_text(content, encoding="utf-8")
    boot_prompt = build_boot_prompt(project_dir)
    return {
        "handoff_path": str(handoff_path),
        "archived_previous": str(archived) if archived else None,
        "validation": validation,
        "boot_prompt": boot_prompt,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate compact HANDOFF.md briefs.")
    parser.add_argument("--validate", type=Path, default=None, help="Validate an existing HANDOFF.md file.")
    parser.add_argument("--project-dir", type=Path, default=Path("."), help="Target project root.")
    parser.add_argument("--goal", default="", help="1-2 sentence goal summary.")
    parser.add_argument("--done", action="append", default=[], help="Completed verified item (repeatable).")
    parser.add_argument("--dead-ends", action="append", default=[], help="Failed approach not to repeat (repeatable).")
    parser.add_argument("--files", action="append", default=[], help="Active file path and role (repeatable).")
    parser.add_argument("--next-action", default="", help="Next concrete step for fresh session.")
    parser.add_argument("--no-archive", action="store_true", help="Do not archive previous HANDOFF.md.")
    parser.add_argument("--copy-prompt", action="store_true", help="Copy boot prompt to macOS clipboard.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    if args.validate is not None:
        vpath = args.validate.resolve()
        res = validate_handoff(vpath.read_text(encoding="utf-8"))
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            status = "VALID" if res["valid"] else "INVALID"
            print(f"HANDOFF_{status} (words={res['words']}/{res['max_words']}, est_tokens={res['est_tokens']})")
            for err in res["errors"]:
                print(f"  ERROR: {err}")
        return 0 if res["valid"] else 1

    project_dir = args.project_dir.resolve()
    result = write_handoff(
        project_dir=project_dir,
        goal=args.goal,
        done=args.done,
        dead_ends=args.dead_ends,
        active_files=args.files,
        next_action=args.next_action,
        archive_old=not args.no_archive,
    )
    copied = copy_to_clipboard(result["boot_prompt"]) if args.copy_prompt else False
    result["copied_to_clipboard"] = copied

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        v = result["validation"]
        print(f"HANDOFF_WRITTEN: {result['handoff_path']} ({v['words']}/{v['max_words']} words, ~{v['est_tokens']} tokens)")
        if result["archived_previous"]:
            print(f"ARCHIVED_PREVIOUS: {result['archived_previous']}")
        if copied:
            print("COPIED_BOOT_PROMPT=TRUE (paste into New Chat)")
        print("\n--- Boot Prompt ---\n" + result["boot_prompt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
