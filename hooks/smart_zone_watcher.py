#!/usr/bin/env python3
"""Zero-token Antigravity PreInvocation hook watching Smart Zone thresholds."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import load_json, save_json  # noqa: E402

DEFAULT_MAX_INVOCATIONS = int(os.environ.get("HANDOFF_MAX_INVOCATIONS", "16"))
DEFAULT_MAX_BYTES = int(os.environ.get("HANDOFF_MAX_BYTES", "55000"))
DEFAULT_COOLDOWN_INVOCATIONS = int(os.environ.get("HANDOFF_COOLDOWN", "6"))
DEFAULT_MAX_RECENT_ERRORS = int(os.environ.get("HANDOFF_MAX_RECENT_ERRORS", "3"))
TAIL_WINDOW_STEPS = 6


def _transcript_stats(transcript_path_str: str, tail_window: int = TAIL_WINDOW_STEPS) -> tuple[int, int, int]:
    if not transcript_path_str:
        return 0, 0, 0
    path = Path(transcript_path_str)
    if not path.is_file():
        return 0, 0, 0
    try:
        raw = path.read_bytes()
    except OSError:
        return 0, 0, 0
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    recent_errors = 0
    for raw_line in lines[-tail_window:]:
        try:
            entry = json.loads(raw_line.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            continue
        if str(entry.get("status", "")).upper() == "ERROR" or entry.get("is_error") is True:
            recent_errors += 1
    return len(raw), len(lines), recent_errors


def evaluate_preinvocation(
    payload: dict[str, Any],
    max_invocations: int = DEFAULT_MAX_INVOCATIONS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    cooldown: int = DEFAULT_COOLDOWN_INVOCATIONS,
    max_recent_errors: int = DEFAULT_MAX_RECENT_ERRORS,
) -> dict[str, Any]:
    """Check invocation count, transcript size, and recent error loops without calling any LLM."""
    inv_num = int(payload.get("invocationNum") or 0)
    transcript_bytes, transcript_lines, recent_errors = _transcript_stats(str(payload.get("transcriptPath") or ""))

    over_inv = inv_num >= max_invocations
    over_bytes = transcript_bytes >= max_bytes
    over_errors = recent_errors >= max_recent_errors
    if not (over_inv or over_bytes or over_errors):
        return {}

    cwd = Path(payload.get("cwd") or ".").resolve()
    conv_id = str(payload.get("conversationId") or "default")
    state_path = cwd / ".handoffs" / "watcher_state.json"

    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = load_json(state_path)
        except (OSError, json.JSONDecodeError):
            state = {}

    last_warn_inv = int(state.get(conv_id, {}).get("last_warn_invocation", -999))
    if (inv_num - last_warn_inv) < cooldown:
        return {}

    state[conv_id] = {"last_warn_invocation": inv_num, "last_bytes": transcript_bytes}
    try:
        save_json(state_path, state)
    except OSError:
        pass

    kb = round(transcript_bytes / 1024.0, 1)
    triggers = []
    if over_errors:
        triggers.append(f"error-loop={recent_errors}/{TAIL_WINDOW_STEPS} recent steps")
    if over_inv or over_bytes:
        triggers.append(f"turn={inv_num}, transcript={kb} KB ({transcript_lines} steps)")
    reason = ", ".join(triggers)
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": (
                        f"Smart Zone notice ({reason}): context rot risk detected. "
                        "Offer to run /context-handoff to write HANDOFF.md (including Dead Ends) and rotate to a clean chat."
                    ),
                    "metadata": {
                        "user_markdown": (
                            f"> **Smart Zone Watcher:** Triggered on `{reason}`. "
                            "Run `/context-handoff` anytime to save `HANDOFF.md` and start a fresh chat."
                        )
                    },
                }
            }
        ]
    }


def main() -> int:
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    print(json.dumps(evaluate_preinvocation(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
