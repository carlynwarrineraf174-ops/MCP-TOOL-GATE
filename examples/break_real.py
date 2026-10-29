""""改坏真实靶场"：从 real-v1 派生 real-v2，注入 6 处破坏。

    python examples/break_real.py            # 生成 snapshots/real-v2
    python -m gate.check --base snapshots/real-v1 --head snapshots/real-v2
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT =  Path(__file__).resolve().parent.parent


def main() -> None:
    src = ROOT / "snapshots" / "real-v1" / "tools.json"
    dst = ROOT / "snapshots" / "real-v2" / "tools.json"
    tools = json.loads(src.read_text(encoding="utf-8"))
    broken = copy.deepcopy(tools)

    # ① 删掉一个入参 —— 应当判 BREAKING (prop_removed)
    if "ms" in broken["slow"]["input_schema"]["properties"]:
        broken["slow"]["input_schema"]["properties"].pop("ms", None)

    # ② 加一个必填参数 —— 应当判 BREAKING (prop_added_required / required_added)
    if "text" in broken["echo"]["input_schema"]["properties"]:
        broken["echo"]["input_schema"]["properties"]["repeat"] = {"type": "integer"}
        broken["echo"]["input_schema"]["required"].append("repeat")

    # ③ 缩一个 enum —— 应当判 BREAKING (enum_shrunk)
    if "reason" in broken["boom"]["input_schema"]["properties"]:
        broken["boom"]["input_schema"]["properties"]["reason"]["enum"] = ["error"]

    # ④ 删一个返回字段 —— 应当判 BREAKING (response_prop_removed)
    if "output_schema" in broken["add"] and broken["add"]["output_schema"]:
        if "properties" in broken["add"]["output_schema"]:
            if "result" in broken["add"]["output_schema"]["properties"]:
                broken["add"]["output_schema"]["properties"].pop("result", None)

    # ⑤ 改一个 description —— 应当判 RISKY (description_changed)
    broken["echo"]["description"] = "回显输入的文本（修改版）。"

    # ⑥ 加一个全新工具 —— 应当判 SAFE (tool_added)
    broken["health_check"] = {
        "description": "健康检查。",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": None,
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(broken, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 已生成 {dst.relative_to(ROOT)}（注入 6 处破坏）")


if __name__ == "__main__":
    main()