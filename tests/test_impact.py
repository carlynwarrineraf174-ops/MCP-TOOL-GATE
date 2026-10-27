"""影响面归因的回归测试：版本一致性 + 受损 case 口径（以前每轮全对、现在有错）。"""

import json
import tempfile
import unittest
from pathlib import Path

from gate.impact import compute


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def eval_report(per_case: list[dict]) -> dict:
    return {"sut": "real", "n": len(per_case), "rounds": 3,
            "tool_acc": 1.0, "args_acc": 0.8, "both_acc": 0.8, "per_case": per_case}


def case(cid: str, tool: str, tool_rate: float = 1.0, args_rate: float = 1.0) -> dict:
    return {"id": cid, "expected": tool, "tool_ok_rate": tool_rate, "args_ok_rate": args_rate}


class ImpactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _reports(self, report_base="snapshots/v1", report_head="snapshots/v2") -> None:
        write_json(self.d / "eval_v1_real.json", eval_report([
            case("c1", "slow"), case("c2", "echo"),
        ]))
        write_json(self.d / "eval_v2_real.json", eval_report([
            case("c1", "slow", args_rate=0.67), case("c2", "echo"),
        ]))
        write_json(self.d / "report.json", {
            "base": report_base, "head": report_head,
            "findings": [
                {"tool": "slow", "kind": "prop_removed", "severity": "BREAKING"},
                {"tool": "other", "kind": "tool_added", "severity": "SAFE"},
            ],
        })

    def test_attribution_when_versions_match(self):
        self._reports()
        r = compute("v1", "v2", str(self.d))
        self.assertEqual(r["broken"], ["c1"])
        self.assertEqual(r["reasons"], ["slow.prop_removed (BREAKING)"])
        self.assertIsNone(r["warn"])

    def test_version_mismatch_warns_and_skips_attribution(self):
        """report.json 是别的版本对 → 只报警、不给原因，且不能崩。"""
        self._reports(report_base="snapshots/demo-v1", report_head="snapshots/demo-v2")
        r = compute("v1", "v2", str(self.d))
        self.assertIn("不一致", r["warn"])
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["broken"], ["c1"])      # 受损 case 仍能算，只是不归因

    def test_case_that_was_already_flaky_is_not_counted(self):
        """base 本来就只对 2/3 轮 → 不算受损（避免把抖动的 case 算成回归）。"""
        write_json(self.d / "eval_v1_real.json", eval_report([case("c1", "slow", args_rate=0.67)]))
        write_json(self.d / "eval_v2_real.json", eval_report([case("c1", "slow", args_rate=0.0)]))
        r = compute("v1", "v2", str(self.d))
        self.assertEqual(r["broken"], [])

    def test_missing_eval_raises(self):
        with self.assertRaises(FileNotFoundError):
            compute("nope", "v2", str(self.d))

    def test_legacy_boolean_per_case_still_works(self):
        """兼容旧版 eval 输出（per_case 存布尔而不是比率）。"""
        write_json(self.d / "eval_v1_real.json", eval_report([
            {"id": "c1", "expected": "slow", "tool_ok": True, "args_ok": True}]))
        write_json(self.d / "eval_v2_real.json", eval_report([
            {"id": "c1", "expected": "slow", "tool_ok": True, "args_ok": False}]))
        r = compute("v1", "v2", str(self.d))
        self.assertEqual(r["broken"], ["c1"])


if __name__ == "__main__":
    unittest.main()
