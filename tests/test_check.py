"""门禁 CLI 的端到端测试：退出码才是 CI 真正消费的东西。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gate.check import main


def write_snapshot(root: Path, name: str, tools: dict) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tools.json").write_text(json.dumps(tools, ensure_ascii=False), encoding="utf-8")
    return d


def weather(input_schema: dict) -> dict:
    return {"t": {"description": "查天气", "input_schema": input_schema, "output_schema": None}}


V1 = weather({"type": "object", "properties": {"city": {"type": "string"}}})
V2_BREAKING = weather({"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})
V2_RISKY = {"t": {"description": "查实时天气", "input_schema": V1["t"]["input_schema"], "output_schema": None}}


class CheckExitCodeTest(unittest.TestCase):
    def run_check(self, old: dict, new: dict, *extra: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = write_snapshot(root, "v1", old)
            head = write_snapshot(root, "v2", new)
            return main(["--base", str(base), "--head", str(head),
                         "--report-dir", str(root / "reports"), "--quiet", *extra])

    def test_breaking_fails(self):
        self.assertEqual(self.run_check(V1, V2_BREAKING), 1)

    def test_no_change_passes(self):
        self.assertEqual(self.run_check(V1, V1), 0)

    def test_risky_passes_by_default_fails_with_flag(self):
        self.assertEqual(self.run_check(V1, V2_RISKY), 0)
        self.assertEqual(self.run_check(V1, V2_RISKY, "--fail-on", "risky"), 1)

    def test_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = write_snapshot(root, "v1", V1)
            head = write_snapshot(root, "v2", V2_BREAKING)
            main(["--base", str(base), "--head", str(head), "--report-dir", str(root / "reports"), "--quiet"])
            md = (root / "reports" / "report.md").read_text(encoding="utf-8")
            self.assertIn("required_added", md)
            self.assertIn("判定规则目录", md)


if __name__ == "__main__":
    unittest.main()
