"""gate/eval.py —— 极简版 Agent 评测引擎。

跑法：python -m gate.eval --cases cases/tool_selection.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .predict import predict

from sut.agent import run_real_agent
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate.eval", description="跑测试用例，算工具和参数的准确率")
    ap.add_argument("--cases", required=True, help="考卷 JSON 文件的路径")
    ap.add_argument("--sut", choices=["fake","real"], default="fake", help="用真模型还是假模型")
    ap.add_argument("--snapshot", default="snapshots/real-v1",help = "使用哪个快照作为工具集")
    args = ap.parse_args(argv)

    # 1. 读取考卷
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))

    total = len(cases)
    tool_correct = 0
    args_correct = 0

    print(f"=== 开始评测，共 {total} 道题 ===")

    # 2. 逐题考试
    for c in cases:
        case_id = c["id"]
        query = c["input"]
        expected_tool = c["expected_tool"]
        expected_args = c.get("expected_args", {})

        # 让假模型答题
        if args.sut == "fake":
            result = predict(query)
        else:
            result = run_real_agent(query, snapshot_dir = args.snapshot)
        actual_tool = result.get("tool")
        actual_args = result.get("args", {})

        # 3. 判卷子：工具选对没？
        tool_ok = (actual_tool == expected_tool)
        if tool_ok:
            tool_correct += 1

        # 4. 判卷子：参数填对没？（只有工具选对了，参数才有意义）
        args_ok = False
        if tool_ok:
            # 这里简化一下：只要实际的参数包含期望的参数，就算对（不要求完全一样）
            args_ok = all(actual_args.get(k) == v for k, v in expected_args.items())
            if args_ok:
                args_correct += 1

        # 打印这一题的得分情况
        status = "✅" if (tool_ok and args_ok) else "❌"
        print(f"[{status}] {case_id} 提问: {query}")
        print(f"      期望调用: {expected_tool}")
        print(f"      实际调用: {actual_tool} (工具{'对' if tool_ok else '错'}, 参数{'对' if args_ok else '错'})")

    # 5. 算总分
    acc_tool = tool_correct / total
    acc_args = args_correct / total

    print("\n=== 成绩单 ===")
    print(f"工具选择准确率 (tool_acc): {acc_tool:.2%}")
    print(f"参数填写准确率 (args_acc): {acc_args:.2%}")

    # 保存 JSON
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    report_file = out_dir / f"eval_{Path(args.snapshot).name}.json"
    report_data = {
        "sut": args.sut,
        "snapshot": args.snapshot,
        "total": total,
        "tool_acc": acc_tool,  # <--- 改这里，存比例
        "args_acc": acc_args  # <--- 改这里，存比例
    }

    report_file.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"评测数据已保存至: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())