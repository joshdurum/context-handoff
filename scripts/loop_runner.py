#!/usr/bin/env python3
"""Autonomous fresh-session runner chaining isolated claude -p batches with circuit breakers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _common import load_json, save_json  # noqa: E402
from build_handoff import write_handoff  # noqa: E402


def _build_session_prompt(project_dir: Path, batch: list[dict[str, Any]], dry_run: bool = False) -> str:
    has_agents = (project_dir / "AGENTS.md").is_file()
    has_handoff = (project_dir / "HANDOFF.md").is_file()
    boot_files = []
    if has_agents:
        boot_files.append("AGENTS.md")
    if has_handoff:
        boot_files.append("HANDOFF.md")

    header = (
        f"First read {', '.join(boot_files)} to get ground truth and Dead Ends."
        if boot_files
        else "Inspect the current working directory first."
    )
    task_lines = []
    for task in batch:
        line = f"- [{task['id']}] {task['title']}: {task['prompt']}"
        if task.get("verify_cmd"):
            line += f" (Must pass: `{task['verify_cmd']}`)"
        task_lines.append(line)

    return (
        f"{header}\n"
        "You are running in a fresh, isolated context window.\n"
        "Complete ONLY this task batch cleanly, run verification checks, and do not touch unrelated scope:\n"
        + "\n".join(task_lines)
        + ("\n[DRY_RUN_MODE]" if dry_run else "")
    )


def default_claude_executor(
    prompt: str,
    project_dir: Path,
    model: str,
    effort: str,
    max_budget_usd: float,
    setting_sources: str | None,
) -> dict[str, Any]:
    """Run a single fresh, isolated claude -p session and parse JSON telemetry."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--effort",
        effort,
        "--no-session-persistence",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read,Write,Edit,Bash",
        "--exclude-dynamic-system-prompt-sections",
        "--output-format",
        "json",
        "--max-budget-usd",
        f"{max_budget_usd:.2f}",
    ]
    if setting_sources:
        cmd.extend(["--setting-sources", setting_sources])

    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, timeout=240)
    elapsed = round(time.monotonic() - t0, 2)

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or f"claude exited {proc.returncode}")[-300:],
            "cost_usd": 0.0,
            "duration_ms": int(elapsed * 1000),
            "usage": {},
        }

    data = json.loads(proc.stdout)
    usage = data.get("usage", {})
    return {
        "ok": not bool(data.get("is_error", False)),
        "result": data.get("result", ""),
        "error": data.get("result", "")[-300:] if data.get("is_error") else "",
        "cost_usd": round(float(data.get("total_cost_usd", 0.0)), 6),
        "duration_ms": data.get("duration_ms", int(elapsed * 1000)),
        "num_turns": data.get("num_turns", 1),
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        },
    }


def _run_verify_commands(batch: list[dict[str, Any]], project_dir: Path) -> tuple[bool, str]:
    for task in batch:
        cmd = (task.get("verify_cmd") or "").strip()
        if not cmd:
            continue
        proc = subprocess.run(cmd, shell=True, cwd=str(project_dir), capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            msg = tail[-1] if tail else f"exit={proc.returncode}"
            return False, f"{task['id']} verify_cmd failed: {msg[:180]}"
    return True, "all verify_cmd passed"


def _maybe_git_commit(project_dir: Path, batch_ids: list[str]) -> bool:
    if not (project_dir / ".git").exists():
        return False
    subprocess.run(["git", "add", "-A"], cwd=str(project_dir), check=False, capture_output=True, timeout=10)
    msg = f"chore(loop): complete {', '.join(batch_ids)}"
    proc = subprocess.run(["git", "commit", "-m", msg], cwd=str(project_dir), capture_output=True, text=True, timeout=10)
    return proc.returncode == 0


def run_loop(
    project_dir: Path,
    tasks_path: Path,
    batch_size: int = 1,
    max_iterations: int = 5,
    max_failures: int = 2,
    model: str = "sonnet",
    effort: str = "medium",
    max_budget_usd: float = 1.00,
    setting_sources: str | None = None,
    git_commit: bool = False,
    dry_run: bool = False,
    executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute pending tasks across isolated fresh sessions until done or circuit-broken."""
    batch_size = max(1, min(3, batch_size))
    tasks_data = load_json(tasks_path)
    tasks: list[dict[str, Any]] = tasks_data.get("tasks", [])
    project_goal = tasks_data.get("goal") or f"Complete tasks for {tasks_data.get('project', project_dir.name)}"
    exec_fn = executor or default_claude_executor

    done_items: list[str] = [f"{t['id']}: {t['title']}" for t in tasks if t.get("status") == "done"]
    dead_ends: list[str] = list(tasks_data.get("dead_ends", []))
    iterations_log: list[dict[str, Any]] = []
    halted_reason = "completed"

    for iteration in range(1, max_iterations + 1):
        pending = [t for t in tasks if t.get("status", "pending") == "pending"]
        if not pending:
            halted_reason = "completed"
            break

        batch = pending[:batch_size]
        batch_ids = [t["id"] for t in batch]
        prompt = _build_session_prompt(project_dir, batch, dry_run=dry_run)

        if dry_run:
            exec_res = {
                "ok": True,
                "cost_usd": 0.0,
                "duration_ms": 0,
                "num_turns": 0,
                "usage": {"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 0},
                "dry_run_prompt": prompt,
            }
            verify_ok, verify_msg = True, "dry-run skipped verify_cmd"
        else:
            exec_res = exec_fn(
                prompt=prompt,
                project_dir=project_dir,
                model=model,
                effort=effort,
                max_budget_usd=max_budget_usd,
                setting_sources=setting_sources,
            )
            if exec_res.get("ok"):
                verify_ok, verify_msg = _run_verify_commands(batch, project_dir)
            else:
                verify_ok, verify_msg = False, exec_res.get("error", "executor failed")

        batch_passed = bool(exec_res.get("ok")) and verify_ok
        tripped_breaker = False

        if batch_passed:
            for t in batch:
                t["status"] = "done"
                done_items.append(f"{t['id']}: {t['title']}")
            if git_commit and not dry_run:
                _maybe_git_commit(project_dir, batch_ids)
        else:
            dead_ends.append(f"Batch {','.join(batch_ids)} failed: {verify_msg}")
            for t in batch:
                t["attempts"] = int(t.get("attempts", 0)) + 1
                if t["attempts"] >= max_failures:
                    t["status"] = "blocked"
                    tripped_breaker = True

        remaining = [t for t in tasks if t.get("status", "pending") == "pending"]
        next_action = (
            f"Execute [{remaining[0]['id']}] {remaining[0]['title']}"
            if remaining
            else "All pending tasks finished; run final verification."
        )

        handoff_info = write_handoff(
            project_dir=project_dir,
            goal=project_goal,
            done=done_items[-6:],
            dead_ends=dead_ends[-5:],
            active_files=[],
            next_action=next_action,
            archive_old=True,
        )

        iterations_log.append({
            "iteration": iteration,
            "task_ids": batch_ids,
            "passed": batch_passed,
            "verify_detail": verify_msg,
            "cost_usd": exec_res.get("cost_usd", 0.0),
            "duration_ms": exec_res.get("duration_ms", 0),
            "num_turns": exec_res.get("num_turns", 0),
            "usage": exec_res.get("usage", {}),
            "handoff_words": handoff_info["validation"]["words"],
        })

        tasks_data["tasks"] = tasks
        tasks_data["dead_ends"] = dead_ends[-8:]
        save_json(tasks_path, tasks_data)

        if tripped_breaker:
            halted_reason = "circuit_breaker_max_failures"
            break
    else:
        if any(t.get("status", "pending") == "pending" for t in tasks):
            halted_reason = "max_iterations_reached"

    all_done = all(t.get("status") == "done" for t in tasks)
    summary = {
        "completed_all": all_done,
        "halted_reason": halted_reason,
        "iterations_run": len(iterations_log),
        "total_cost_usd": round(sum(float(x["cost_usd"]) for x in iterations_log), 6),
        "done_count": sum(1 for t in tasks if t.get("status") == "done"),
        "blocked_count": sum(1 for t in tasks if t.get("status") == "blocked"),
        "pending_count": sum(1 for t in tasks if t.get("status", "pending") == "pending"),
        "iterations": iterations_log,
    }
    save_json(project_dir / ".handoffs" / "loop_log.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run tasks across isolated fresh claude -p sessions.")
    parser.add_argument("--project-dir", type=Path, default=Path("."))
    parser.add_argument("--tasks", type=Path, default=Path("tasks.json"))
    parser.add_argument("--batch-size", type=int, default=1, help="Tasks per fresh session (1-3).")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--max-failures", type=int, default=2, help="Circuit breaker failures per task.")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--max-budget-usd", type=float, default=1.00)
    parser.add_argument("--setting-sources", default=None)
    parser.add_argument("--git-commit", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    tasks_path = args.tasks if args.tasks.is_absolute() else (project_dir / args.tasks)
    summary = run_loop(
        project_dir=project_dir,
        tasks_path=tasks_path.resolve(),
        batch_size=args.batch_size,
        max_iterations=args.max_iterations,
        max_failures=args.max_failures,
        model=args.model,
        effort=args.effort,
        max_budget_usd=args.max_budget_usd,
        setting_sources=args.setting_sources,
        git_commit=args.git_commit,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"LOOP_FINISHED (completed_all={summary['completed_all']}, reason={summary['halted_reason']}, "
            f"done={summary['done_count']}, blocked={summary['blocked_count']}, cost=${summary['total_cost_usd']})"
        )
    return 0 if summary["completed_all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
