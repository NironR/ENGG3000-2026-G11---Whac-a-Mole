import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

GAME_FILE = Path(__file__).resolve().parents[1] / "whacka.py"


# Runs the named whacka.py functions inside `scope` (without starting the GUI) and returns it.
def load_functions(names, scope):
    tree = ast.parse(GAME_FILE.read_text(encoding="utf-8-sig"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(functions) == len(names), "a function was renamed or removed"
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(GAME_FILE), "exec"), scope)
    return scope


# Game state for one active mole 0.1 s into a 2 s up-time (a 100-point hit), with the GUI and
# audio replaced by harmless stand-ins. `scheduled` collects what root.after() was asked to run.
def special_mole_scope(mole_type, scheduled, **overrides):
    scope = {
        "score": 0, "combo": 0, "successful_hits": 0, "current_difficulty": "Easy",
        "game_running": True, "game_paused": False, "game_ended_by_ta": False,
        "current_mole_type": mole_type,
        "golden_hammer_active": False, "golden_hammer_ends_at": 0.0,
        "combo_shield_active": False, "hammer_image_size": (1, 1),

        "mole": {"x_m": 0.5, "y_m": 0.7}, "mole_state": "active",
        "cursor_x_m": 0.5, "cursor_y_m": 0.7, "WHACK_RADIUS_M": 0.20,
        "mole_active_duration_ms": 2000, "mole_active_started_at": 99.9,
        "time": SimpleNamespace(monotonic=lambda: 100.0),

        "time_remaining": 58, "ROUND_DURATION": 60,
        "TIME_MOLE_BONUS": 5, "GOLDEN_HAMMER_DURATION_S": 5,
        "mole_timer": None, "mole_animation_timer": None, "MOLE_HIT_DURATION_MS": 225,

        "score_label": SimpleNamespace(config=lambda **kwargs: None),
        "root": SimpleNamespace(after=lambda ms, func: scheduled.append(func) or "timer"),
        "draw_hud": lambda: None,
        "start_hammer_strike": lambda: None,
        "draw_mole_sprite": lambda: None,
        "start_mole_fall": "start_mole_fall",
        "end_round": "end_round",
        "audio": SimpleNamespace(
            play_whack=lambda: None,
            play_effect=lambda name: 0,
            play_music=lambda name: None
        )
    }
    scope.update(overrides)
    return scope


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

    def test_special_mole_hits(self):
        # Input: mole type, expected (score, combo, time left, golden hammer, shield, next step)
        test_cases = [
            ("normal", 100, 1, 58, False, False, "start_mole_fall"),
            ("golden", 200, 1, 58, True, False, "start_mole_fall"),   # x2 from the hit itself
            ("time", 100, 1, 60, False, False, "start_mole_fall"),    # 58 + 5 capped at 60
            ("combo", 100, 2, 58, False, True, "start_mole_fall"),    # +2 combo and a shield
            ("ta", 0, 0, 58, False, False, "end_round")               # no score, round ends
        ]

        for mole_type, points, combo, time_left, golden, shield, next_step in test_cases:
            with self.subTest(mole_type=mole_type):
                scheduled = []
                scope = load_functions(
                    {"check_whack", "get_hit_points", "update_difficulty"},
                    special_mole_scope(mole_type, scheduled)
                )

                scope["check_whack"]()

                self.assertEqual(scope["score"], points)
                self.assertEqual(scope["combo"], combo)
                self.assertEqual(scope["time_remaining"], time_left)
                self.assertEqual(scope["golden_hammer_active"], golden)
                self.assertEqual(scope["combo_shield_active"], shield)
                self.assertEqual(scheduled, [next_step])
                self.assertEqual(scope["game_running"], mole_type != "ta")
                self.assertEqual(scope["game_ended_by_ta"], mole_type == "ta")
                if golden:
                    # Lasts GOLDEN_HAMMER_DURATION_S from the hit
                    self.assertEqual(scope["golden_hammer_ends_at"], 105.0)

    def test_mouse_on_mole_picture(self):
        # The mole is in the front hole; its picture also covers part of the back hole's outline
        front = {"row": 1, "col": 0, "x_m": 0.25, "y_m": 1.05}
        back = {"row": 0, "col": 0, "x_m": 0.25, "y_m": 0.35}
        bounds = {id(front): (0, 100, 50, 150), id(back): (0, 0, 50, 50)}
        scope = load_functions({"pointer_to_metres"}, {
            "mole": front,
            "holes": [back, front],
            "mole_image_id": "mole sprite",
            "MOUSE_CLAMP_TO_PLAYFIELD": False,
            "canvas_to_metres": lambda px, py, clamp: ("playfield", px, py),
            "get_hole_bounds": lambda hole, scale: bounds[id(hole)],
            "container": SimpleNamespace(
                # the mole picture spans y 20..150 on the canvas
                find_overlapping=lambda x1, y1, x2, y2: ["mole sprite"] if 20 <= y1 <= 150 else []
            )
        })
        to_metres = scope["pointer_to_metres"]

        # On the mole's picture, outside any other hole: counts as the mole's hole
        self.assertEqual(to_metres(25, 80), (0.25, 1.05))
        # On the picture but inside the back hole's outline: stays the back hole
        self.assertEqual(to_metres(25, 30), ("playfield", 25, 30))
        # Off the picture: wherever the pointer really is
        self.assertEqual(to_metres(25, 10), ("playfield", 25, 10))

    def test_missed_moles(self):
        # Input: mole type, shield up, expected (combo, shield) after the mole hides unhit
        test_cases = [
            ("normal", False, 0, False),   # a miss resets the combo
            ("normal", True, 4, False),    # the shield saves it once
            ("ta", False, 4, False),       # letting Iain hide is not a miss
            ("ta", True, 4, True)          # ...and doesn't use up the shield
        ]

        for mole_type, shield, combo, shield_after in test_cases:
            with self.subTest(mole_type=mole_type, shield=shield):
                scheduled = []
                scope = load_functions(
                    {"hide_mole", "update_difficulty"},
                    special_mole_scope(
                        mole_type, scheduled,
                        combo=4, combo_shield_active=shield,
                        start_mole_fall=lambda: scheduled.append("fall")
                    )
                )

                scope["hide_mole"]()

                self.assertEqual(scope["combo"], combo)
                self.assertEqual(scope["combo_shield_active"], shield_after)
                self.assertEqual(scheduled, ["fall"])


if __name__ == "__main__":
    unittest.main()
