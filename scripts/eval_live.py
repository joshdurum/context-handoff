#!/usr/bin/env python3
"""Run Stage 2/3 live Claude Code evals for context-handoff (Trigger + Autonomous Loop + A/B Efficiency)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _common import estimate_tokens, load_json, parse_frontmatter, save_json, word_count  # noqa: E402
from build_handoff import validate_handoff, write_handoff  # noqa: E402
from loop_runner import run_loop  # noqa: E402

DISTRACTOR_SKILLS = [
    {
        "name": "build-prompt",
        "description": "Guide a novice through clarifying questions to compile a token-optimized prompt.",
    },
    {
        "name": "init-project-gates",
        "description": "Audit a repository stack and write Verification Gates into AGENTS.md and CLAUDE.md.",
    },
    {
        "name": "rubric-gate",
        "description": "Evaluate task complexity and enforce strict True/False quality rubrics backed by automated tests.",
    },
]


def _run_claude(args: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    cmd = ["claude", "-p", *args]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    elapsed = round(time.monotonic() - t0, 2)
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed (exit {proc.returncode}): {proc.stderr or proc.stdout}")
    data = json.loads(proc.stdout)
    data["_wall_seconds"] = elapsed
    return data


def run_trigger_eval(skill_dir: Path, model: str = "haiku") -> dict[str, Any]:
    """Evaluate U2 Trigger Precision against tests/trigger_cases.json."""
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(skill_md)
    triggers = load_json(skill_dir / "tests" / "trigger_cases.json")
    catalog = [{"name": meta["name"], "description": meta["description"]}, *DISTRACTOR_SKILLS]

    schema = json.dumps({
        "type": "object",
        "properties": {
            "should_activate_context_handoff": {"type": "boolean"},
            "chosen_skill": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["should_activate_context_handoff", "chosen_skill", "reason"],
        "additionalProperties": False,
    })

    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for expected, key in [(True, "should_trigger"), (False, "should_not_trigger")]:
            for prompt in triggers[key]:
                router_prompt = (
                    "You are an agent skill router. Given these available skills:\n"
                    f"{json.dumps(catalog, indent=2)}\n\n"
                    f"User request: {prompt!r}\n\n"
                    "Decide strictly whether `context-handoff` should be activated for this request."
                )
                raw = _run_claude(
                    [
                        router_prompt,
                        "--model",
                        model,
                        "--effort",
                        "low",
                        "--safe-mode",
                        "--no-session-persistence",
                        "--tools",
                        "",
                        "--output-format",
                        "json",
                        "--json-schema",
                        schema,
                        "--max-budget-usd",
                        "0.25",
                    ],
                    cwd=tmp_path,
                )
                structured = raw.get("structured_output") or json.loads(raw["result"])
                predicted = bool(structured["should_activate_context_handoff"])
                cases.append({
                    "prompt": prompt,
                    "expected": expected,
                    "predicted": predicted,
                    "passed": predicted == expected,
                    "chosen_skill": structured.get("chosen_skill"),
                    "cost_usd": raw.get("total_cost_usd", 0.0),
                })

    pos_hits = sum(1 for c in cases if c["expected"] and c["passed"])
    neg_fp = sum(1 for c in cases if not c["expected"] and not c["passed"])
    return {
        "u2_passed": pos_hits >= 2 and neg_fp == 0,
        "positive_hits": pos_hits,
        "positive_total": sum(1 for c in cases if c["expected"]),
        "negative_false_positives": neg_fp,
        "negative_total": sum(1 for c in cases if not c["expected"]),
        "cases": cases,
    }


def run_live_autonomous_loop_test(model: str = "haiku") -> dict[str, Any]:
    """Run loop_runner.py end-to-end across 2 genuine fresh claude -p sessions."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp)
        (proj / "AGENTS.md").write_text(
            "# Mini Inbox App\n- Use Python 3 stdlib only (`sqlite3`, `unittest`).\n",
            encoding="utf-8",
        )
        tasks_path = proj / "tasks.json"
        save_json(tasks_path, {
            "project": "mini-inbox",
            "goal": "Build and unit-test a minimal SQLite note inbox in Python stdlib.",
            "tasks": [
                {
                    "id": "T1",
                    "title": "Build SQLite inbox module",
                    "prompt": (
                        "Create inbox.py with init_db(db_path), add_note(db_path, text), "
                        "and list_notes(db_path) returning a list of note strings in insertion order."
                    ),
                    "verify_cmd": (
                        "python3 -c \"import tempfile, pathlib, inbox; "
                        "p = pathlib.Path(tempfile.mkdtemp()) / 'n.db'; "
                        "inbox.init_db(str(p)); inbox.add_note(str(p), 'buy milk'); "
                        "assert inbox.list_notes(str(p)) == ['buy milk']\""
                    ),
                    "status": "pending",
                },
                {
                    "id": "T2",
                    "title": "Write unittest suite for inbox.py",
                    "prompt": "Create test_inbox.py using unittest + tempfile testing add_note and list_notes.",
                    "verify_cmd": "python3 -m unittest test_inbox.py -v",
                    "status": "pending",
                },
            ],
        })

        summary = run_loop(
            project_dir=proj,
            tasks_path=tasks_path,
            batch_size=1,
            max_iterations=3,
            max_failures=2,
            model=model,
            effort="low",
            max_budget_usd=0.50,
            setting_sources="project",
        )

        handoff_text = (proj / "HANDOFF.md").read_text(encoding="utf-8") if (proj / "HANDOFF.md").is_file() else ""
        handoff_val = validate_handoff(handoff_text)
        archives = list((proj / ".handoffs" / "archive").glob("*_HANDOFF.md")) if (proj / ".handoffs" / "archive").is_dir() else []

        return {
            "loop_passed": summary["completed_all"] and summary["iterations_run"] == 2 and handoff_val["valid"],
            "completed_all": summary["completed_all"],
            "iterations_run": summary["iterations_run"],
            "done_count": summary["done_count"],
            "total_cost_usd": summary["total_cost_usd"],
            "final_handoff_words": handoff_val["words"],
            "archived_handoffs_count": len(archives),
            "iterations": summary["iterations"],
        }


def _noisy_transcript_dump() -> str:
    """Simulate a bloated ~1,700-word messy conversation log from an unrotated session."""
    filler_turn = (
        "Assistant: Let's try using pyyaml and tinydb to store the notes in ./notes.db first! "
        "Wait, let me inspect the directory... oh, actually maybe tinydb isn't installed? "
        "Let me check another way: what if we parse YAML or save to a hardcoded notes.db path in CWD? "
        "User: Why is that erroring? Can we just make it work cleanly without extra fuss? "
        "Assistant: Good catch, sorry! Earlier I suggested yaml.safe_load and tinydb.TinyDB('./notes.db'), "
        "which failed with ModuleNotFoundError, and hardcoding notes.db breaks test isolation. "
        "Also remember earlier when we thought about CSV vs XML? Forget XML, we talked for 10 minutes about XML schemas "
        "and markdown tables and whether to add Rich colored terminal output, wait let's NOT use rich either "
        "because pip packages aren't installed in the sandbox! Wait did we verify that? Let me re-read the traceback. "
        "Traceback (most recent call last): ModuleNotFoundError: No module named 'yaml'. "
        "User: Okay stop guessing libraries, just keep going and figure out export next.\n"
    )
    return ("=== RAW BLOATED TRANSCRIPT LOG (UNROTATED SESSION) ===\n" + (filler_turn * 9))


def run_ab_handoff_eval(model: str = "haiku") -> dict[str, Any]:
    """Compare bloated transcript resume (Arm A) vs <400-word HANDOFF.md (Arm B)."""
    task_instruction = (
        "Resume the project and create `exporter.py` defining `export_notes(notes, out_path)` "
        "which writes the `notes` list as JSON to `out_path` and returns the written Path or string."
    )
    verify_cmd = (
        "python3 -c \"import json, pathlib, tempfile, exporter; "
        "p = pathlib.Path(tempfile.mkdtemp()) / 'out.json'; "
        "exporter.export_notes(['a', 'b'], str(p)); "
        "assert json.loads(p.read_text()) == ['a', 'b']\""
    )

    with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
        path_a, path_b = Path(dir_a), Path(dir_b)

        raw_dump = _noisy_transcript_dump()
        prompt_a = f"{raw_dump}\n\nNow do the next step:\n{task_instruction}"

        handoff_res = write_handoff(
            project_dir=path_b,
            goal="Create a Python stdlib note exporter module.",
            done=["Confirmed Python 3 stdlib is available"],
            dead_ends=[
                "Do NOT import yaml/pyyaml, tinydb, or rich (not installed).",
                "Do NOT hardcode ./notes.db; always write to the caller's out_path argument.",
            ],
            active_files=["exporter.py (to be created)"],
            next_action=task_instruction,
            archive_old=False,
        )
        prompt_b = f"{handoff_res['boot_prompt']}\n\nTask detail:\n{task_instruction}"

        flags = [
            "--model",
            model,
            "--effort",
            "low",
            "--setting-sources",
            "project",
            "--no-session-persistence",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read,Write,Edit,Bash",
            "--output-format",
            "json",
            "--max-budget-usd",
            "0.50",
        ]

        raw_a = _run_claude([prompt_a, *flags], cwd=path_a)
        raw_b = _run_claude([prompt_b, *flags], cwd=path_b)

        def grade_arm(work_dir: Path, prompt_text: str, raw_resp: dict[str, Any]) -> dict[str, Any]:
            exp = work_dir / "exporter.py"
            code = exp.read_text(encoding="utf-8") if exp.is_file() else ""
            avoided_dead_ends = bool(code) and not any(bad in code for bad in ["import yaml", "tinydb", "import rich", "notes.db"])
            verify_ok = False
            if exp.is_file():
                proc = subprocess.run(verify_cmd, shell=True, cwd=str(work_dir), capture_output=True, text=True, timeout=15)
                verify_ok = proc.returncode == 0
            usage = raw_resp.get("usage", {})
            handoff_file = work_dir / "HANDOFF.md"
            context_words = word_count(prompt_text) + (word_count(handoff_file.read_text(encoding="utf-8")) if handoff_file.is_file() else 0)
            return {
                "passed_functional_verify": verify_ok,
                "avoided_dead_ends": avoided_dead_ends,
                "context_words_sent": context_words,
                "context_est_tokens": estimate_tokens(prompt_text) + (estimate_tokens(handoff_file.read_text(encoding="utf-8")) if handoff_file.is_file() else 0),
                "cost_usd": round(float(raw_resp.get("total_cost_usd", 0.0)), 6),
                "duration_ms": raw_resp.get("duration_ms"),
                "output_tokens": usage.get("output_tokens", 0),
            }

        arm_a = grade_arm(path_a, prompt_a, raw_a)
        arm_b = grade_arm(path_b, prompt_b, raw_b)

    token_reduction_pct = round(
        (1.0 - (arm_b["context_est_tokens"] / max(arm_a["context_est_tokens"], 1))) * 100.0, 1
    )
    return {
        "u1_efficiency_and_quality_win": (
            arm_b["passed_functional_verify"]
            and arm_b["avoided_dead_ends"]
            and arm_b["context_est_tokens"] < arm_a["context_est_tokens"]
        ),
        "handoff_context_token_reduction_pct": token_reduction_pct,
        "arm_a_bloated_transcript": arm_a,
        "arm_b_context_handoff": arm_b,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live Stage 2/3 evals for context-handoff.")
    parser.add_argument("--skill-dir", type=Path, default=SKILL_ROOT)
    parser.add_argument("--out", type=Path, default=SKILL_ROOT / "tests" / "live_eval_results.json")
    args = parser.parse_args(argv)

    skill_dir = args.skill_dir.resolve()
    trigger_res = run_trigger_eval(skill_dir)
    loop_res = run_live_autonomous_loop_test()
    ab_res = run_ab_handoff_eval()

    report = {
        "skill": "context-handoff",
        "trigger_eval_u2": trigger_res,
        "autonomous_loop_live": loop_res,
        "ab_handoff_eval_u1": ab_res,
    }
    save_json(args.out.resolve(), report)
    print(json.dumps(report, indent=2))
    passed = trigger_res["u2_passed"] and loop_res["loop_passed"] and ab_res["u1_efficiency_and_quality_win"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
