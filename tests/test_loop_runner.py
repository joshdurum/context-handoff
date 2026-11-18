"""Unit tests for scripts/loop_runner.py."""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _common import load_json, save_json  # noqa: E402
from loop_runner import run_loop  # noqa: E402


class TestLoopRunner(unittest.TestCase):
    def test_dry_run_processes_all_batches_without_calling_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_path = tmp_path / "tasks.json"
            save_json(tasks_path, {
                "project": "demo",
                "goal": "Run two dry batches",
                "tasks": [
                    {"id": "T1", "title": "First", "prompt": "Do 1", "status": "pending"},
                    {"id": "T2", "title": "Second", "prompt": "Do 2", "status": "pending"},
                    {"id": "T3", "title": "Third", "prompt": "Do 3", "status": "pending"},
                ],
            })
            summary = run_loop(tmp_path, tasks_path, batch_size=2, max_iterations=5, dry_run=True)
            self.assertTrue(summary["completed_all"])
            self.assertEqual(summary["iterations_run"], 2)
            self.assertEqual(summary["done_count"], 3)
            self.assertTrue((tmp_path / "HANDOFF.md").is_file())
            self.assertTrue((tmp_path / ".handoffs" / "loop_log.json").is_file())

    def test_fresh_sessions_pass_verify_and_update_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_path = tmp_path / "tasks.json"
            save_json(tasks_path, {
                "project": "mini-app",
                "goal": "Create and verify module.py",
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Create module.py",
                        "prompt": "Write add()",
                        "verify_cmd": "python3 -c \"import module; assert module.add(2, 3) == 5\"",
                        "status": "pending",
                    }
                ],
            })

            def fake_exec(prompt: str, project_dir: Path, **_: object) -> dict:
                (project_dir / "module.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                return {"ok": True, "cost_usd": 0.01, "duration_ms": 120, "num_turns": 1, "usage": {"input_tokens": 50}}

            summary = run_loop(tmp_path, tasks_path, executor=fake_exec)
            self.assertTrue(summary["completed_all"])
            self.assertEqual(summary["total_cost_usd"], 0.01)
            self.assertEqual(load_json(tasks_path)["tasks"][0]["status"], "done")

    def test_circuit_breaker_halts_after_max_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_path = tmp_path / "tasks.json"
            save_json(tasks_path, {
                "project": "broken-app",
                "goal": "Test circuit breaker",
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Failing check",
                        "prompt": "Broken",
                        "verify_cmd": "python3 -c \"import sys; sys.exit(1)\"",
                        "status": "pending",
                    }
                ],
            })

            def noop_exec(prompt: str, project_dir: Path, **_: object) -> dict:
                return {"ok": True, "cost_usd": 0.005, "duration_ms": 50, "num_turns": 1, "usage": {}}

            summary = run_loop(tmp_path, tasks_path, max_iterations=5, max_failures=2, executor=noop_exec)
            self.assertFalse(summary["completed_all"])
            self.assertEqual(summary["halted_reason"], "circuit_breaker_max_failures")
            self.assertEqual(summary["iterations_run"], 2)
            self.assertEqual(summary["blocked_count"], 1)
            handoff_text = (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")
            self.assertIn("T1 verify_cmd failed", handoff_text)


if __name__ == "__main__":
    unittest.main()
