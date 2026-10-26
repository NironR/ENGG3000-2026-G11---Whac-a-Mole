import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

GAME_FILE = Path(__file__).resolve().parents[1] / "whacka.py"


class TestGameplay(unittest.TestCase):

    def test_difficulty_thresholds(self):
        # Read actual V3 game code without starting GUI
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "update_difficulty"
        ]

        self.assertEqual(len(functions), 1)

        # Set up test variables
        scope = {
            "successful_hits": 0,
            "combo": 0,
            "current_difficulty": "Easy",
            "game_running": False
        }

        exec(
            compile(
                ast.Module(body=functions, type_ignores=[]),
                str(GAME_FILE),
                "exec"
            ),
            scope
        )

        # Input: successful hits, combo, expected level
        test_cases = [
            (0, 0, "Easy"),
            (7, 0, "Easy"),
            (8, 0, "Medium"),
            (19, 0, "Medium"),
            (20, 0, "Hard"),
            (0, 3, "Medium"),
            (0, 5, "Hard"),
            (8, 5, "Hard")
        ]

        for hits, combo, expected in test_cases:
            with self.subTest(hits=hits, combo=combo):
                scope["successful_hits"] = hits
                scope["combo"] = combo

                scope["update_difficulty"]()

                self.assertEqual(
                    scope["current_difficulty"],
                    expected
                )

    def test_reaction_time_scoring(self):
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8-sig"))

        # Extract real V3 scoring and difficulty functions
        names = {
            "check_whack",
            "get_hit_points",
            "update_difficulty"
        }

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in names
        ]

        self.assertEqual(
            {node.name for node in functions},
            names
        )

        # elapsed time, starting combo, points, final combo, difficulty
        test_cases = [
            (100, 0, 100, 1, "Easy"),
            (500, 2, 200, 3, "Medium"),
            (1000, 4, 225, 5, "Hard"),
            (1500, 0, 50, 1, "Easy"),
            (1800, 0, 25, 1, "Easy")
        ]

        for elapsed_ms, starting_combo, expected_points, expected_combo, expected_level in test_cases:
            with self.subTest(elapsed_ms=elapsed_ms, combo=starting_combo):

                scope = {
                    "score": 0,
                    "combo": starting_combo,
                    "successful_hits": 0,
                    "current_difficulty": "Easy",
                    "game_running": False,

                    "mole": {"x_m": 0.5, "y_m": 0.7},
                    "mole_state": "active",
                    "cursor_x_m": 0.5,
                    "cursor_y_m": 0.7,
                    "WHACK_RADIUS_M": 0.20,

                    "mole_active_duration_ms": 2000,
                    "mole_active_started_at": 100 - elapsed_ms / 1000,
                    "time": SimpleNamespace(monotonic=lambda: 100.0),

                    "time_remaining": 59,
                    "ROUND_DURATION": 60,
                    "HIT_TIME_BONUS": 1,

                    "mole_timer": None,
                    "mole_animation_timer": None,
                    "MOLE_HIT_DURATION_MS": 225,

                    # Replace GUI actions with harmless test objects
                    "score_label": SimpleNamespace(
                        config=lambda **kwargs: None
                    ),
                    "root": SimpleNamespace(
                        after=lambda *args: "timer"
                    ),
                    "draw_hud": lambda: None,
                    "start_hammer_strike": lambda: None,
                    "draw_mole_sprite": lambda: None,
                    "start_mole_fall": lambda: None,
                    "audio": SimpleNamespace(
                        play_whack=lambda: None
                    )
                }

                exec(
                    compile(
                        ast.Module(body=functions, type_ignores=[]),
                        str(GAME_FILE),
                        "exec"
                    ),
                    scope
                )

                scope["check_whack"]()

                self.assertEqual(scope["score"], expected_points)
                self.assertEqual(scope["combo"], expected_combo)
                self.assertEqual(scope["current_difficulty"], expected_level)
                self.assertEqual(scope["time_remaining"], 60)
                self.assertEqual(scope["mole_state"], "hit")


if __name__ == "__main__":
    unittest.main()