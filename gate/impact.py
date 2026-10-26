"""gate/impact.py —— 影响面归因：计算契约变更对模型准确率的实际影响。"""

from __future__ import annotations
import json
from pathlib import Path

def main() -> int:
    base_file = Path("reports/eval_real-v1.json")
    head_file = Path("reports/eval_real-v2.json")

    if not base_file.exists() or not head_file.exists():
        print("缺少评测数据，请先运行 eval 生成 JSON。")
        return 1

    base = json.loads(base_file.read_text(encoding="utf-8"))
    head = json.loads(head_file.read_text(encoding="utf-8"))

    base_tool = base["tool_acc"]
    head_tool = head["tool_acc"]
    base_args = base["args_acc"]
    head_args = head["args_acc"]

    delta_tool = (head_tool - base_tool) * 100
    delta_args = (head_args - base_args) * 100

    print("=== 影响面归因报告 ===")
    print(f"基准版本: {base['snapshot']}")
    print(f"对比版本: {head['snapshot']}")
    print(f"工具选择准确率: {base_tool:.2%} -> {head_tool:.2%} (Δ {delta_tool:+.2f} pp)")
    print(f"参数填写准确率: {base_args:.2%} -> {head_args:.2%} (Δ {delta_args:+.2f} pp)")

    # 追加写入到人类可读的 report.md
    md_file = Path("reports/report.md")
    if md_file.exists():
        impact_section = f"""
## 影响面归因（由 LLM 评测得出）

- 基准版本：`{base['snapshot']}`
- 变更版本：`{head['snapshot']}`
- **工具选择准确率变化**：{base_tool:.2%} → {head_tool:.2%} （**Δ {delta_tool:+.2f} pp**）
- **参数填写准确率变化**：{base_args:.2%} → {head_args:.2%} （**Δ {delta_args:+.2f} pp**）
"""
        with open(md_file, "a", encoding="utf-8") as f:
            f.write(impact_section)
        print(f"影响面数据已追加至: {md_file}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())