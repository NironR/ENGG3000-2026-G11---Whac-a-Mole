import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


GAME_FILE = Path(__file__).resolve().parents[1] / "whacka.py"


class TestLeaderboard(unittest.TestCase):

    def test_sorting_and_saving(self):
        # Use a temporary folder to protect real player scores
        with tempfile.TemporaryDirectory() as folder:

            test_file = Path(folder) / "leaderboard.json"

            # Extract actual leaderboard functions without starting the GUI
            tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

            names = {
                "load_leaderboard",
                "save_leaderboard",
                "add_leaderboard_score"
            }

            functions = [
                node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name in names
            ]

            self.assertEqual(len(functions), 3)

            scope = {
                "json": json,
                "os": os,
                "tempfile": tempfile,
                "LEADERBOARD_FILE": str(test_file),
                "MAX_LEADERBOARD_ENTRIES": 5
            }

            exec(
                compile(
                    ast.Module(body=functions, type_ignores=[]),
                    str(GAME_FILE),
                    "exec"
                ),
                scope
            )

            # Add three test players
            scope["add_leaderboard_score"]("Test1", 9)
            scope["add_leaderboard_score"]("Test2", 15)
            scope["add_leaderboard_score"]("Test3", 12)

            # Check leaderboard order
            leaderboard = scope["load_leaderboard"]()

            scores = [entry["score"] for entry in leaderboard]

            self.assertEqual(scores, [15, 12, 9])

            # Check JSON file was saved
            self.assertTrue(test_file.exists())

    def test_invalid_json_handling(self):
        # Extract the actual load_leaderboard function
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "load_leaderboard"
        ]

        self.assertEqual(len(functions), 1)

        with tempfile.TemporaryDirectory() as folder:
            test_file = Path(folder) / "leaderboard.json"

            scope = {
                "json": json,
                "LEADERBOARD_FILE": str(test_file),
                "MAX_LEADERBOARD_ENTRIES": 5
            }

            exec(
                compile(
                    ast.Module(body=functions, type_ignores=[]),
                    str(GAME_FILE),
                    "exec"
                ),
                scope
            )

            # Test A: Broken JSON syntax
            test_file.write_text("{invalid json", encoding="utf-8")
            self.assertEqual(scope["load_leaderboard"](), [])

            # Test B: Valid JSON but incorrect structure
            test_file.write_text(
                '{"name": "Test", "score": "abc"}',
                encoding="utf-8"
            )
            self.assertEqual(scope["load_leaderboard"](), [])

            # Test C: Mixed valid and invalid records
            test_file.write_text(
                json.dumps([
                    {"name": "Alice", "score": 20},
                    {"name": "Bob", "score": "wrong"},
                    {"name": "", "score": 15},
                    {"name": "Charlie", "score": 10}
                ]),
                encoding="utf-8"
            )

            result = scope["load_leaderboard"]()

            self.assertEqual(
                [entry["score"] for entry in result],
                [20, 10]
            )

    def test_top_five_limit(self):
        # Extract real leaderboard functions
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

        names = {
            "load_leaderboard",
            "save_leaderboard",
            "add_leaderboard_score"
        }

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in names
        ]

        self.assertEqual(len(functions), 3)

        with tempfile.TemporaryDirectory() as folder:
            test_file = Path(folder) / "leaderboard.json"

            scope = {
                "json": json,
                "os": os,
                "tempfile": tempfile,
                "LEADERBOARD_FILE": str(test_file),
                "MAX_LEADERBOARD_ENTRIES": 5
            }

            exec(
                compile(
                    ast.Module(body=functions, type_ignores=[]),
                    str(GAME_FILE),
                    "exec"
                ),
                scope
            )

            # Add six players
            scores = [10, 50, 30, 20, 40, 60]

            for i, score in enumerate(scores, start=1):
                scope["add_leaderboard_score"](
                    f"Player{i}", score
                )

            # Check only the top five remain
            leaderboard = scope["load_leaderboard"]()

            self.assertEqual(len(leaderboard), 5)

            self.assertEqual(
                [entry["score"] for entry in leaderboard],
                [60, 50, 40, 30, 20]
            )

            # Verify saved JSON also contains only five entries
            saved_data = json.loads(
                test_file.read_text(encoding="utf-8")
            )

            self.assertEqual(len(saved_data), 5)

    def test_save_failure_preserves_data(self):
        # Extract actual leaderboard functions
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

        names = {
            "load_leaderboard",
            "save_leaderboard",
            "add_leaderboard_score"
        }

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in names
        ]

        self.assertEqual(len(functions), 3)

        with tempfile.TemporaryDirectory() as folder:
            test_file = Path(folder) / "leaderboard.json"

            original_data = [
                {"name": "Alice", "score": 50}
            ]

            test_file.write_text(
                json.dumps(original_data),
                encoding="utf-8"
            )

            scope = {
                "json": json,
                "os": os,
                "tempfile": tempfile,
                "LEADERBOARD_FILE": str(test_file),
                "MAX_LEADERBOARD_ENTRIES": 5
            }

            exec(
                compile(
                    ast.Module(body=functions, type_ignores=[]),
                    str(GAME_FILE),
                    "exec"
                ),
                scope
            )

            # Simulate failure when replacing old file
            with patch.object(
                os,
                "replace",
                side_effect=OSError("Simulated save failure")
            ):
                with self.assertRaises(OSError):
                    scope["add_leaderboard_score"](
                        "NewPlayer", 999
                    )

            # Original leaderboard must remain unchanged
            saved_data = json.loads(
                test_file.read_text(encoding="utf-8")
            )

            self.assertEqual(saved_data, original_data)

            # Temporary files should be cleaned up
            temporary_files = list(
                Path(folder).glob("leaderboard_*.tmp")
            )

            self.assertEqual(temporary_files, [])

    def test_repeated_score_submissions(self):
        # Extract real leaderboard functions
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

        names = {
            "load_leaderboard",
            "save_leaderboard",
            "add_leaderboard_score"
        }

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in names
        ]

        self.assertEqual(len(functions), 3)

        with tempfile.TemporaryDirectory() as folder:
            test_file = Path(folder) / "leaderboard.json"

            scope = {
                "json": json,
                "os": os,
                "tempfile": tempfile,
                "LEADERBOARD_FILE": str(test_file),
                "MAX_LEADERBOARD_ENTRIES": 5
            }

            exec(
                compile(
                    ast.Module(body=functions, type_ignores=[]),
                    str(GAME_FILE),
                    "exec"
                ),
                scope
            )

            # Simulate 100 consecutive score submissions
            for i in range(100):
                scope["add_leaderboard_score"](
                    f"Player{i}", i
                )

            leaderboard = scope["load_leaderboard"]()

            # Only the five highest scores should remain
            self.assertEqual(len(leaderboard), 5)

            self.assertEqual(
                [entry["score"] for entry in leaderboard],
                [99, 98, 97, 96, 95]
            )

            # Verify saved data is still valid JSON
            saved_data = json.loads(
                test_file.read_text(encoding="utf-8")
            )

            self.assertEqual(saved_data, leaderboard)


if __name__ == "__main__":
    unittest.main()