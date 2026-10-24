"""门禁 CLI：读两份快照 → 出报告 → 用退出码卡住 CI。

    python -m gate.check --base snapshots/v1 --head snapshots/v2
    echo $LASTEXITCODE      # 1 = 有 BREAKING，CI 应当失败

报告落盘：
    reports/report.json     机器读（CI 里塞进 artifact）
    reports/report.md       人读（贴 PR 评论）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .diff import diff_snapshots
from .rules import BREAKING, ORDER, RISKY, SAFE, rule_catalog_markdown, worst

_LEVELS = (BREAKING, RISKY, SAFE)


def load_tools(snapshot_dir: Path) -> dict:
    path = snapshot_dir / "tools.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少 {path}，先跑 python -m gate.snapshot --out {snapshot_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def render_console(findings: list, base: str, head: str) -> str:
    counts = {lv: sum(1 for f in findings if f.severity == lv) for lv in _LEVELS}
    lines = [
        f"base={base}  head={head}",
        f"worst={worst(findings)}  BREAKING={counts[BREAKING]}  RISKY={counts[RISKY]}  SAFE={counts[SAFE]}",
        "-" * 78,
    ]
    if not findings:
        lines.append("(无变更)")
    for f in sorted(findings, key=lambda x: (-ORDER[x.severity], x.tool, x.path)):
        lines.append(f"[{f.severity:<8}] {f.tool:<16} {f.kind:<26} {f.detail}")
    return "\n".join(lines)


def render_markdown(findings: list, base: str, head: str) -> str:
    counts = {lv: sum(1 for f in findings if f.severity == lv) for lv in _LEVELS}
    lines = [
        "# MCP 工具契约变更报告",
        "",
        f"- base: `{base}`",
        f"- head: `{head}`",
        f"- 结论: **{worst(findings)}**（BREAKING {counts[BREAKING]} / RISKY {counts[RISKY]} / SAFE {counts[SAFE]}）",
        "",
        "## 变更明细",
        "",
    ]
    if not findings:
        lines.append("无变更。")
    else:
        lines += ["| 严重度 | 工具 | 规则 | 位置 | 说明 |", "|---|---|---|---|---|"]
        for f in sorted(findings, key=lambda x: (-ORDER[x.severity], x.tool, x.path)):
            lines.append(f"| **{f.severity}** | {f.tool} | `{f.kind}` | `{f.path}` | {f.detail} |")
    lines += ["", "<details><summary>判定规则目录（为什么这么判）</summary>", "", rule_catalog_markdown(), "", "</details>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate.check", description="MCP 工具契约变更门禁")
    ap.add_argument("--base", required=True, help="旧快照目录，例如 snapshots/v1")
    ap.add_argument("--head", required=True, help="新快照目录，例如 snapshots/v2")
    ap.add_argument("--fail-on", choices=["breaking", "risky"], default="breaking",
                    help="达到该档位就退出码 1（默认 breaking）")
    ap.add_argument("--report-dir", default="reports", help="报告输出目录")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印明细")
    args = ap.parse_args(argv)

    try:
        old_tools = load_tools(Path(args.base))
        new_tools = load_tools(Path(args.head))
    except FileNotFoundError as exc:
        print(f"[error] {exc}")
        return 2

    findings = diff_snapshots(old_tools, new_tools)
    level = worst(findings)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "base": args.base,
                "head": args.head,
                "worst": level,
                "counts": {lv: sum(1 for f in findings if f.severity == lv) for lv in _LEVELS},
                "findings": [f.__dict__ for f in findings],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(render_markdown(findings, args.base, args.head), encoding="utf-8")

    if not args.quiet:
        print(render_console(findings, args.base, args.head))
        print(f"报告已写入: {report_dir / 'report.md'}")

    threshold = BREAKING if args.fail_on == "breaking" else RISKY
    if ORDER[level] >= ORDER[threshold]:
        if not args.quiet:
            print(f"[gate] 失败：worst={level} >= 阈值={args.fail_on}")
        return 1
    if not args.quiet:
        print(f"[gate] 通过：worst={level} < 阈值={args.fail_on}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
