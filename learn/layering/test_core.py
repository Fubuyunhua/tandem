"""内核的测试，相当于"纸面病例"：不联网、不看时钟、不随机，毫秒级跑完。

运行：在本目录执行  python -m unittest -v
"""
import ast
import pathlib
import unittest

import core


class AfterCi(unittest.TestCase):
    def test_green_means_done(self):
        self.assertEqual(core.after_ci(True, 0, 12)["action"], "done")

    def test_red_retries_until_limit(self):
        self.assertEqual(core.after_ci(False, 0, 12)["action"], "retry")
        self.assertEqual(core.after_ci(False, 1, 12)["action"], "retry")

    def test_red_after_limit_asks_human(self):
        decision = core.after_ci(False, 2, 12)
        self.assertEqual(decision["action"], "ask_human")
        self.assertIn("PR 12", decision["card"]["title"])

    def test_counts_only_this_prs_retries(self):
        events = [
            {"pr": 12, "action": "retry"},
            {"pr": 99, "action": "retry"},
            {"pr": 12, "action": "retry"},
            {"pr": 12, "action": "done"},
        ]
        self.assertEqual(core.attempts_so_far(events, 12), 2)


class QuietHours(unittest.TestCase):
    # 白天就能测半夜的行为——因为时间是参数，不是内核自己读的
    def test_daytime_pushes(self):
        self.assertTrue(core.should_push(15, "C"))

    def test_night_holds_non_urgent(self):
        self.assertFalse(core.should_push(23, "C"))
        self.assertFalse(core.should_push(3, "C"))

    def test_night_still_pushes_level_d(self):
        self.assertTrue(core.should_push(23, "D"))

    def test_boundary_eight_am_is_not_quiet(self):
        self.assertTrue(core.should_push(8, "C"))


class Boundary(unittest.TestCase):
    """边界守卫：内核不准 import 碰外部世界的模块。"""

    FORBIDDEN = {"world", "datetime", "time", "random", "os", "subprocess", "socket", "urllib", "requests", "sqlite3"}

    def test_core_imports_nothing_from_outside(self):
        source = pathlib.Path(core.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported & self.FORBIDDEN, set(), "core.py 越界了：内核不能碰外部世界")


if __name__ == "__main__":
    unittest.main()
