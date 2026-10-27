"""评测口径的回归测试：三个分数必须各算各的。"""
import unittest
from gate.eval import score_once, summarize


CASES = [
    {"id": "a", "input": "x", "expected_tool": "t1", "expected_args": {"k": 1}},
    {"id": "b", "input": "y", "expected_tool": "t2", "expected_args": {"k": 2}},
]


class EvalMetricTest(unittest.TestCase):
    def test_all_correct(self):
        r = score_once(CASES, lambda c: {"tool": c["expected_tool"], "args": c["expected_args"]})
        self.assertEqual((r["tool_acc"], r["args_acc"], r["both_acc"]), (1.0, 1.0, 1.0))

    def test_args_acc_is_conditional_on_tool(self):
        """工具选错、参数值恰好对：args_acc 不该被拉低（它是条件口径）。"""
        preds = {"a": {"tool": "t1", "args": {"k": 1}},
                 "b": {"tool": "t9", "args": {"k": 2}}}
        r = score_once(CASES, lambda c: preds[c["id"]])
        self.assertEqual(r["tool_acc"], 0.5)
        self.assertEqual(r["args_acc"], 1.0)   # 选对的那次参数是对的
        self.assertEqual(r["both_acc"], 0.5)

    def test_no_tool_correct_does_not_crash(self):
        r = score_once(CASES, lambda c: {"tool": "nope", "args": {}})
        self.assertEqual((r["tool_acc"], r["args_acc"], r["both_acc"]), (0.0, 0.0, 0.0))

    def test_summarize_reports_range(self):
        runs = [{"tool_acc": 0.8, "args_acc": 0.7, "both_acc": 0.6},
                {"tool_acc": 1.0, "args_acc": 0.9, "both_acc": 0.8}]
        s = summarize(runs)
        self.assertEqual(s["tool"]["min"], 0.8)
        self.assertEqual(s["tool"]["max"], 1.0)
        self.assertAlmostEqual(s["tool"]["mean"], 0.9)


if __name__ == "__main__":
    unittest.main()