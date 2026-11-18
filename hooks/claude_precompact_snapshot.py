#!/usr/bin/env python3
"""Deterministic Claude Code PreCompact hook: save user prompts & edited files to .handoffs/."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any


def _extract_transcript_summary(transcript_path: Path) -> tuple[list[str], list[str]]:
    prompts: list[str] = []
    touched_files: list[str] = []
    if not transcript_path.is_file():
        return prompts, touched_files

    for raw_line in transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        msg_type = str(entry.get("type") or entry.get("role") or "").lower()
        content = entry.get("content") or entry.get("message", {}).get("content")
        if msg_type in {"user", "user_input"} and isinstance(content, str) and content.strip():
            prompts.append(" ".join(content.strip().split())[:180])

        tool_calls = entry.get("tool_calls") or []
        if isinstance(content, list):
            tool_calls = [*tool_calls, *[b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]]
        for call in tool_calls:
            name = str(call.get("name") or "").lower()
            args = call.get("input") or call.get("args") or {}
            if isinstance(args, dict) and name in {"edit", "write", "edit_file", "write_file"}:
                fpath = args.get("file_path") or args.get("Path") or args.get("path")
                if fpath and fpath not in touched_files:
                    touched_files.append(str(fpath))

    return prompts[-5:], touched_files[-15:]


def create_precompact_snapshot(payload: dict[str, Any]) -> Path | None:
    """Scrape transcript_path deterministically and write .handoffs/precompact_backup.md."""
    cwd = Path(payload.get("cwd") or ".").resolve()
    tpath_str = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")
    if not tpath_str:
        return None

    prompts, files = _extract_transcript_summary(Path(tpath_str))
    out_dir = cwd / ".handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "precompact_backup.md"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"# PreCompact Snapshot ({stamp})",
        "",
        "## Recent User Prompts",
        *([f"- {p}" for p in prompts] or ["- (none detected)"]),
        "",
        "## Files Modified in Transcript",
        *([f"- `{f}`" for f in files] or ["- (none detected)"]),
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> int:
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    create_precompact_snapshot(payload)
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
