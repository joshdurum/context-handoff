"""Unit tests for scripts/build_handoff.py."""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_handoff import MAX_HANDOFF_WORDS, validate_handoff, write_handoff  # noqa: E402


class TestBuildHandoff(unittest.TestCase):
    def test_validates_strict_five_sections_and_word_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            info = write_handoff(
                project_dir=tmp_path,
                goal="Build SQLite capture CLI.",
                done=["Created store.py"],
                dead_ends=["Avoid PyYAML; not installed"],
                active_files=["`store.py` — SQLite helpers"],
                next_action="Run test_store.py",
            )
            self.assertTrue(info["validation"]["valid"])
            self.assertLessEqual(info["validation"]["words"], MAX_HANDOFF_WORDS)
            self.assertIn("AGENTS.md", info["boot_prompt"])
            self.assertTrue((tmp_path / "HANDOFF.md").is_file())

    def test_rejects_over_400_words_and_missing_dead_ends(self) -> None:
        too_long = "# Session Handoff\n\n## Goal\n" + ("word " * 405)
        res_long = validate_handoff(too_long)
        self.assertFalse(res_long["valid"])
        self.assertTrue(any("exceeds limit" in e for e in res_long["errors"]))

        missing_dead_ends = (
            "# Session Handoff\n\n## Goal\nTest\n\n## Verified Done\n- x\n\n"
            "## Active Files\n- a.py\n\n## Next Exact Action\nRun tests\n"
        )
        res_missing = validate_handoff(missing_dead_ends)
        self.assertFalse(res_missing["valid"])
        self.assertTrue(any("Dead Ends" in e for e in res_missing["errors"]))

    def test_archives_previous_handoff_before_writing_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_handoff(tmp_path, "Goal 1", ["T1"], [], ["a.py"], "Do T2")
            second = write_handoff(tmp_path, "Goal 1", ["T1", "T2"], ["Failed X"], ["a.py"], "Done")
            self.assertIsNotNone(second["archived_previous"])
            self.assertTrue(Path(second["archived_previous"]).is_file())


if __name__ == "__main__":
    unittest.main()
