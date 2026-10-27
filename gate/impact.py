"""gate/impact.py —— 影响面归因：漂移 → 受损 case → 对应 finding。

它回答的不是"准确率掉了几个点"，而是：
    **这次契约变更，让哪几条用例从"全对"变成"有错"，又是哪条变更造成的？**

前提：先跑 `gate.check`（生成 report.json）和两次 `gate.eval --sut real`
（生成 reports/eval_<name>_real.json，per_case 是多轮聚合率）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rate(case: dict, key: str) -> float:
    """读多轮聚合率；兼容旧版 eval 的布尔字段（tool_ok / args_ok）。"""
    if key in case:
        return float(case[key])
    fallback = key.replace("_rate", "")          # tool_ok_rate -> tool_ok
    return 1.0 if case.get(fallback) else 0.0


def _is_all_correct(case: dict) -> bool:
    return _rate(case, "tool_ok_rate") == 1.0 and _rate(case, "args_ok_rate") == 1.0


def broken_cases(base: dict, head: dict) -> tuple[list[str], set[str]]:
    """base 里"每轮都对"、head 里"出现过错"的 case → (case id 列表, 涉及的工具集合)。"""
    base_pc = {c["id"]: c for c in base.get("per_case", [])}
    broken: list[str] = []
    tools: set[str] = set()
    for h in head.get("per_case", []):
        b = base_pc.get(h["id"])
        if b is None:
            continue
        # 只在「以前全对」的 case 上算受损，避免把本来就错的 case 也算进来
        if _is_all_correct(b) and not _is_all_correct(h):
            broken.append(h["id"])
            if b.get("expected"):
                tools.add(b["expected"])
    return broken, tools


def attribute(report: dict, base_name: str, head_name: str, tools: set[str],
              findings: list[dict]) -> str | None:
    """校验 report.json 与本次 eval 是不是同一对版本；返回 warn 文案（None = 一致）。"""
    r_base = Path(str(report.get("base", ""))).name
    r_head = Path(str(report.get("head", ""))).name
    if (r_base, r_head) != (base_name, head_name):
        return (f"[warn] report.json 是 {r_base} → {r_head}，与本次 {base_name} → "
                f"{head_name} 不一致 → **不做原因归因**（先跑一次匹配的 gate.check）")
    return None


def compute(base_name: str, head_name: str, reports_dir: str = "reports") -> dict:
    """纯计算：不打印、不写文件，方便单测。"""
    d = Path(reports_dir)
    base_file, head_file = d / f"eval_{base_name}_real.json", d / f"eval_{head_name}_real.json"
    if not base_file.exists() or not head_file.exists():
        raise FileNotFoundError(
            f"缺少评测数据：需要 {base_file} 和 {head_file}"
            f"（先跑 python -m gate.eval --sut real --snapshot snapshots/{base_name}）"
        )

    base = json.loads(base_file.read_text(encoding="utf-8"))
    head = json.loads(head_file.read_text(encoding="utf-8"))
    broken, tools = broken_cases(base, head)

    reasons: list[str] = []
    warn: str | None = None
    report_file = d / "report.json"
    if report_file.exists():
        report = json.loads(report_file.read_text(encoding="utf-8"))
        warn = attribute(report, base_name, head_name, tools, report.get("findings", []))
        if warn is None:
            for f in report.get("findings", []):
                if f.get("tool") in tools:
                    reasons.append(f"{f['tool']}.{f['kind']} ({f['severity']})")
    else:
        warn = "[warn] 找不到 reports/report.json → 不做原因归因（先跑一次 gate.check）"

    return {
        "base": base_name,
        "head": head_name,
        "base_tool": base["tool_acc"],
        "head_tool": head["tool_acc"],
        "base_args": base["args_acc"],
        "head_args": head["args_acc"],
        "broken": broken,
        "reasons": sorted(set(reasons)),
        "warn": warn,
    }


def render_markdown(r: dict) -> str:
    dt = (r["head_tool"] - r["base_tool"]) * 100
    da = (r["head_args"] - r["base_args"]) * 100
    lines = [
        "# 影响面归因报告", "",
        f"- 基准版本：`{r['base']}`　→　变更版本：`{r['head']}`",
        f"- **工具选择准确率**：{r['base_tool']:.2%} → {r['head_tool']:.2%}（**Δ {dt:+.2f} pp**）",
        f"- **参数填写准确率**：{r['base_args']:.2%} → {r['head_args']:.2%}（**Δ {da:+.2f} pp**）",
        f"- **受损用例**（以前每轮全对、现在有错）：{', '.join(r['broken']) or '无'}",
        f"- **对应变更**：{' · '.join(r['reasons']) or '未归因'}",
    ]
    if r["warn"]:
        lines.append(f"- {r['warn']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate.impact", description="漂移 → 受损 case → 对应 finding")
    ap.add_argument("--base", default="real-v1", help="基准版本名（对应 snapshots/<name>）")
    ap.add_argument("--head", default="real-v2", help="对比版本名")
    ap.add_argument("--reports-dir", default="reports")
    args = ap.parse_args(argv)

    try:
        r = compute(Path(args.base).name, Path(args.head).name, args.reports_dir)
    except FileNotFoundError as exc:
        print(f"[error] {exc}")
        return 1

    dt = (r["head_tool"] - r["base_tool"]) * 100
    da = (r["head_args"] - r["base_args"]) * 100
    print("=== 影响面归因报告 ===")
    print(f"基准版本: {r['base']} | 对比版本: {r['head']}")
    print(f"工具选择准确率: {r['base_tool']:.2%} -> {r['head_tool']:.2%} (Δ {dt:+.2f} pp)")
    print(f"参数填写准确率: {r['base_args']:.2%} -> {r['head_args']:.2%} (Δ {da:+.2f} pp)")
    print(f"受影响的具体用例: {', '.join(r['broken']) or '无'}")
    print(f"对应变更原因: {' · '.join(r['reasons']) or '未归因'}")
    if r["warn"]:
        print(r["warn"])

    dest = Path(args.reports_dir) / "impact.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_markdown(r), encoding="utf-8")      # 覆盖写，不追加
    print(f"影响面数据已写入: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
