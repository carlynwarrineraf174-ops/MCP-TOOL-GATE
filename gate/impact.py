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

    # 读取 report.json 获取具体变更原因，并做一致性校验
    report_file = Path("reports/report.json")
    change_reasons = []
    if report_file.exists():
        report = json.loads(report_file.read_text(encoding="utf-8"))

        # 保护机制：防止拿 demo 靶场的报告去解释 real 靶场的错误
        if report.get("base").split("/")[-1] != base_name or report.get("head").split("/")[-1] != head_name:
            print(f"[warn] report.json 是 {report.get('base')} → {report.get('head')}，与本次 {base_name} → {head_name} 不一致，原因可能张冠李戴")
        else:
            # 找出受损用例
            base_per_case = {c["id"]: c for c in base["per_case"]}
            head_per_case = {c["id"]: c for c in head["per_case"]}

            broken_cases = []
            broken_tools = set()

            for cid, h_case in head_per_case.items():
                b_case = base_per_case.get(cid)
                # 以前全对 (rate == 1.0)，现在出现了错误 (rate < 1.0)
                if b_case and b_case["tool_ok_rate"] == 1.0 and b_case["args_ok_rate"] == 1.0:
                    if h_case["tool_ok_rate"] < 1.0 or h_case["args_ok_rate"] < 1.0:
                        broken_cases.append(cid)
                        broken_tools.add(b_case["expected"])

            for f in report.get("findings", []):
                if f["tool"] in broken_tools:
                    change_reasons.append(f"{f['tool']}.{f['kind']} ({f['severity']})")

    print("=== 影响面归因报告 ===")
    print(f"基准版本: {args.base} | 对比版本: {args.head}")
    print(f"工具选择准确率: {base_tool:.2%} -> {head_tool:.2%} (Δ {delta_tool:+.2f} pp)")
    print(f"参数填写准确率: {base_args:.2%} -> {head_args:.2%} (Δ {delta_args:+.2f} pp)")
    print(f"⚠️ 受影响的具体用例: {', '.join(broken_cases) if broken_cases else '无'}")
    print(f"🔍 对应变更原因: {' · '.join(change_reasons) if change_reasons else '无'}")

    # 覆盖写入
    md_file = Path("reports/impact.md")
    md_file.parent.mkdir(parents=True, exist_ok=True)
    impact_section = f"""# 影响面归因报告

- 基准版本：`{args.base}`
- 变更版本：`{args.head}`
- **工具选择准确率变化**：{base_tool:.2%} → {head_tool:.2%} （**Δ {delta_tool:+.2f} pp**）
- **参数填写准确率变化**：{base_args:.2%} → {head_args:.2%} （**Δ {delta_args:+.2f} pp**）
- **受损用例清单**：{', '.join(broken_cases) if broken_cases else '无'}
- **对应变更原因**：{' · '.join(change_reasons) if change_reasons else '无'}
"""
    md_file.write_text(impact_section, encoding="utf-8")
    print(f"影响面数据已写入: {md_file}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())