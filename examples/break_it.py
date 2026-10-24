""""改坏实验"：把 v1 快照改坏三处，产出 v2 —— 用来证明门禁真的抓得住。

这是 lab_04 的产品化版本：以前在实验台里改坏别人的引擎，
现在改坏自己的契约，验证自己的门禁。

    python examples/break_it.py            # 生成 snapshots/v2
    python -m gate.check --base snapshots/v1 --head snapshots/v2
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    src = ROOT / "snapshots" / "v1" / "tools.json"
    dst = ROOT / "snapshots" / "v2" / "tools.json"
    tools = json.loads(src.read_text(encoding="utf-8"))
    broken = copy.deepcopy(tools)

    # ① 只改描述 —— 应当判 RISKY（不影响代码，影响模型选工具）
    broken["get_weather"]["description"] = "查询指定城市的实时天气（含湿度）。"

    # ② 删掉一个入参 —— 应当判 BREAKING
    broken["query_order"]["input_schema"]["properties"].pop("with_items", None)

    # ③ 收紧取值范围 —— 应当判 BREAKING
    broken["search_doc"]["input_schema"]["properties"]["top_k"]["maximum"] = 5

    # ④ 新增一个工具 —— 应当判 SAFE（老调用不受影响）
    broken["cancel_order"] = {
        "description": "取消一笔未发货订单。",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
        "output_schema": None,
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(broken, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 已生成 {dst.relative_to(ROOT)}（1 处描述改动 + 1 处删参 + 1 处范围收紧 + 1 个新工具）")


if __name__ == "__main__":
    main()
