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
                    "game_paused": False,
                    "current_mole_type": "normal",
                    "golden_hammer_active": False,
                    "combo_shield_active": False,

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
                        play_whack=lambda: None,
                        play_effect=lambda name: 0
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
                self.assertEqual(scope["time_remaining"], 59)
                self.assertEqual(scope["mole_state"], "hit")

    def test_pause_does_not_eat_up_time(self):
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8-sig"))

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "set_paused"
        ]

        self.assertEqual(len(functions), 1)

        clock = {"now": 100.5}
        scheduled = []

        # Mole came fully up at t=100 with 2000 ms to stay up; Golden Hammer runs out at t=103
        scope = {
            "game_paused": False,
            "pause_label": None,
            "paused_at": 0.0,
            "mole": {"x_m": 0.5, "y_m": 0.7},
            "mole_state": "active",
            "mole_timer": "hide timer",
            "mole_active_started_at": 100.0,
            "mole_active_duration_ms": 2000,
            "golden_hammer_active": True,
            "golden_hammer_ends_at": 103.0,
            "hide_mole": lambda: None,

            "time": SimpleNamespace(monotonic=lambda: clock["now"]),
            "root": SimpleNamespace(
                after=lambda ms, func: scheduled.append(ms) or "new timer",
                after_cancel=lambda timer_id: None
            ),
            "tk": SimpleNamespace(
                Label=lambda *args, **kwargs: SimpleNamespace(
                    place=lambda **kwargs: None,
                    place_forget=lambda: None,
                    lift=lambda: None,
                    winfo_exists=lambda: True
                )
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

        # Pause 0.5 s after the mole came up, resume 10 s later
        scope["set_paused"](True)
        clock["now"] = 110.5
        scope["set_paused"](False)

        # The 10 s pause is added back, so 1500 ms of up-time is still left
        self.assertAlmostEqual(scope["mole_active_started_at"], 110.0)
        self.assertEqual(scheduled, [1500])
        self.assertAlmostEqual(scope["golden_hammer_ends_at"], 113.0)

    def test_auto_pause_needs_every_box(self):
        tree = ast.parse(GAME_FILE.read_text(encoding="utf-8-sig"))

        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "update_pause"
        ]

        self.assertEqual(len(functions), 1)

        # Input: box links, expected pause after 2 s with nobody seen
        test_cases = [
            ({1: "link", 2: "link", 3: "link"}, True),
            ({1: "link", 2: None, 3: "link"}, False),   # a box is down
            ({}, False)                                  # no pySerial: mouse only
        ]

        for links, expected in test_cases:
            with self.subTest(links=links):
                clock = {"now": 100.0}
                pauses = []

                scope = {
                    "game_running": True,
                    "game_paused": False,
                    "player_missing_since": None,
                    "player_gone": 1.0,
                    "box_links": links,
                    "time": SimpleNamespace(monotonic=lambda: clock["now"]),
                    "set_paused": pauses.append
                }

                exec(
                    compile(
                        ast.Module(body=functions, type_ignores=[]),
                        str(GAME_FILE),
                        "exec"
                    ),
                    scope
                )

                scope["update_pause"](False)
                clock["now"] = 102.0
                scope["update_pause"](False)

                self.assertEqual(pauses == [True], expected)


if __name__ == "__main__":
    unittest.main()
