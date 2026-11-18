"""Unit tests for Smart Zone watcher and Claude PreCompact snapshot hooks."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = SKILL_ROOT / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from claude_precompact_snapshot import create_precompact_snapshot  # noqa: E402
from smart_zone_watcher import evaluate_preinvocation  # noqa: E402


class TestContextHooks(unittest.TestCase):
    def test_smart_zone_watcher_triggers_once_and_respects_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text('{"step_index": 1}\n' * 10, encoding="utf-8")

            low = evaluate_preinvocation(
                {"invocationNum": 3, "transcriptPath": str(transcript), "cwd": str(tmp_path), "conversationId": "c1"},
                max_invocations=16,
                max_bytes=55000,
            )
            self.assertEqual(low, {})

            high = evaluate_preinvocation(
                {"invocationNum": 16, "transcriptPath": str(transcript), "cwd": str(tmp_path), "conversationId": "c1"},
                max_invocations=16,
                max_bytes=55000,
                cooldown=6,
            )
            self.assertIn("injectSteps", high)
            self.assertIn("user_markdown", high["injectSteps"][0]["systemMessage"]["metadata"])

            next_turn = evaluate_preinvocation(
                {"invocationNum": 17, "transcriptPath": str(transcript), "cwd": str(tmp_path), "conversationId": "c1"},
                max_invocations=16,
                max_bytes=55000,
                cooldown=6,
            )
            self.assertEqual(next_turn, {})

    def test_claude_precompact_scraper_extracts_prompts_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "claude.jsonl"
            entries = [
                {"type": "user", "content": "Build store.py with sqlite3"},
                {
                    "type": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Write", "input": {"file_path": "/repo/store.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/repo/cli.py"}},
                    ],
                },
            ]
            transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
            backup = create_precompact_snapshot({"cwd": str(tmp_path), "transcript_path": str(transcript)})
            self.assertIsNotNone(backup)
            text = backup.read_text(encoding="utf-8")
            self.assertIn("Build store.py with sqlite3", text)
            self.assertIn("/repo/store.py", text)
            self.assertIn("/repo/cli.py", text)

    def test_smart_zone_watcher_detects_error_loop_content_rot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "transcript.jsonl"
            entries = [
                {"step_index": 1, "status": "DONE"},
                {"step_index": 2, "status": "ERROR"},
                {"step_index": 3, "status": "ERROR"},
                {"step_index": 4, "status": "DONE"},
                {"step_index": 5, "status": "ERROR"},
            ]
            transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

            res = evaluate_preinvocation(
                {"invocationNum": 5, "transcriptPath": str(transcript), "cwd": str(tmp_path), "conversationId": "c_err"},
                max_invocations=16,
                max_bytes=55000,
                max_recent_errors=3,
            )
            self.assertIn("injectSteps", res)
            msg = res["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("error-loop=3/6", msg)


if __name__ == "__main__":
    unittest.main()
