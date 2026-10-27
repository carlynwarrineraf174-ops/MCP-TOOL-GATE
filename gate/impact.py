"""gate/impact.py —— 影响面归因：计算契约变更对模型准确率的实际影响。"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="real-v1", help="基准版本名")
    ap.add_argument("--head", default="real-v2", help="对比版本名")
    args = ap.parse_args()

    # 提取路径的最后一部分，确保无论是 "real-v1" 还是 "snapshots/real-v1" 都能找到
    base_name = Path(args.base).name
    head_name = Path(args.head).name
    base_file = Path(f"reports/eval_{base_name}_real.json")
    head_file = Path(f"reports/eval_{head_name}_real.json")

    if not base_file.exists() or not head_file.exists():
        print(f"缺少评测数据，请先运行 eval 生成 {base_file} 和 {head_file}")
        return 1

    base = json.loads(base_file.read_text(encoding="utf-8"))
    head = json.loads(head_file.read_text(encoding="utf-8"))

    base_tool = base["tool_acc"]
    head_tool = head["tool_acc"]
    base_args = base["args_acc"]
    head_args = head["args_acc"]

    delta_tool = (head_tool - base_tool) * 100
    delta_args = (head_args - base_args) * 100

    # 找出哪些 case 从“对”变成了“错”
    base_per_case = {c["id"]: c for c in base["per_case"]}
    head_per_case = {c["id"]: c for c in head["per_case"]}

    broken_cases = []
    for cid, h_case in head_per_case.items():
        b_case = base_per_case.get(cid)
        if b_case and b_case["tool_ok"] and b_case["args_ok"]: # 以前是对的
            if not h_case["tool_ok"] or not h_case["args_ok"]: # 现在错了
                broken_cases.append(cid)

    print("=== 影响面归因报告 ===")
    print(f"基准版本: {args.base} | 对比版本: {args.head}")
    print(f"工具选择准确率: {base_tool:.2%} -> {head_tool:.2%} (Δ {delta_tool:+.2f} pp)")
    print(f"参数填写准确率: {base_args:.2%} -> {head_args:.2%} (Δ {delta_args:+.2f} pp)")
    print(f"⚠️ 受影响的具体用例: {', '.join(broken_cases) if broken_cases else '无'}")

    # 追加写入到人类可读的 report.md
    md_file = Path("reports/report.md")
    if md_file.exists():
        impact_section = f"""
## 影响面归因（由 LLM 评测得出）

- 基准版本：`{args.base}`
- 变更版本：`{args.head}`
- **工具选择准确率变化**：{base_tool:.2%} → {head_tool:.2%} （**Δ {delta_tool:+.2f} pp**）
- **参数填写准确率变化**：{base_args:.2%} → {head_args:.2%} （**Δ {delta_args:+.2f} pp**）
- **受损用例清单**：{', '.join(broken_cases) if broken_cases else '无'}
"""
        with open(md_file, "a", encoding="utf-8") as f:
            f.write(impact_section)
        print(f"影响面数据已追加至: {md_file}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())