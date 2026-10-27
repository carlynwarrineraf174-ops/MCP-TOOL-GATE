"""gate/eval.py —— 评测引擎。

跑法：
    python -m gate.eval --cases cases/tool_selection.json --sut fake --rounds 3
    python -m gate.eval --cases cases/tool_selection.json --sut real --rounds 3 --snapshot snapshots/real-v1

口径（写进 README，面试必问）：
    tool_acc  工具选对的比例             = tool_ok / n
    args_acc  工具选对时参数也对的比例    = args_ok / tool_ok      ← 条件口径，分母不是 n
    both_acc  一次调用整体正确            = both_ok / n
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Callable

Predict = Callable[[dict], dict]


def ensure_utf8() -> None:
    """Windows 控制台默认 GBK，打印 ✅/→ 会 UnicodeEncodeError。入口调一次。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def score_once(cases: list[dict], predict: Predict) -> dict:
    """跑一轮：逐题判分，返回计数 + 三个准确率 + 每题明细。"""
    tool_ok = args_ok = both_ok = 0
    detail: list[dict] = []

    for case in cases:
        pred = predict(case) or {}
        called = pred.get("tool")
        got_args = pred.get("args") or {}
        expect_args = case.get("expected_args") or {}

        t_ok = called == case.get("expected_tool")
        # 参数只在「工具选对」时才有意义：工具都错了，填对参数是运气不是能力
        a_ok = bool(t_ok and all(got_args.get(k) == v for k, v in expect_args.items()))
        b_ok = bool(t_ok and a_ok)

        tool_ok += int(bool(t_ok))
        args_ok += int(a_ok)
        both_ok += int(b_ok)
        detail.append({"id": case.get("id"), "expected": case.get("expected_tool"),
                       "actual": called, "tool_ok": bool(t_ok), "args_ok": a_ok})

    n = len(cases) or 1
    return {
        "n": len(cases),
        "tool_ok": tool_ok,
        "args_ok": args_ok,
        "both_ok": both_ok,
        "tool_acc": tool_ok / n,
        "args_acc": (args_ok / tool_ok) if tool_ok else 0.0,   # ← 条件分母
        "both_acc": both_ok / n,
        "detail": detail,
    }


def summarize(runs: list[dict]) -> dict:
    """多轮汇总：均值 + [min,max]。单轮的 ±8pp 噪声比要检测的退化还大（lab_05 实测）。"""
    def agg(key: str) -> dict:
        vals = [r[key] for r in runs]
        return {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}

    return {"rounds": len(runs), "tool": agg("tool_acc"), "args": agg("args_acc"),
            "both": agg("both_acc")}


def build_predictor(sut: str, snapshot: str, fake_answers: str) -> Predict:
    if sut == "fake":
        table = json.loads(Path(fake_answers).read_text(encoding="utf-8"))

        def _fake(case: dict) -> dict:
            return table.get(case.get("id"), {"tool": "unknown", "args": {}})

        return _fake

    # 只有真模型这条路才 import langchain —— 保证 --sut fake 不需要装任何模型依赖
    from sut.agent import run_real_agent

    def _real(case: dict) -> dict:
        return run_real_agent(case["input"], snapshot_dir=snapshot)

    return _real


def _fmt(a: dict) -> str:
    return f"{a['mean']:.2%} [{a['min']:.2%}, {a['max']:.2%}]"


def main(argv: list[str] | None = None) -> int:
    ensure_utf8()
    ap = argparse.ArgumentParser(prog="gate.eval", description="跑测试用例，算工具/参数准确率")
    ap.add_argument("--cases", required=True, help="考卷 JSON")
    ap.add_argument("--sut", choices=["fake", "real"], default="fake")
    ap.add_argument("--snapshot", default="snapshots/real-v1", help="用哪个快照当工具集")
    ap.add_argument("--fake-answers", default="cases/fake_answers.json",
                    help="fake 版答案表（验证评测管线本身，不是模型成绩）")
    ap.add_argument("--rounds", type=int, default=3, help="轮次（>=3，单轮不可信）")
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args(argv)

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    predict = build_predictor(args.sut, args.snapshot, args.fake_answers)

    print(f"=== 评测：{len(cases)} case × {args.rounds} 轮，sut={args.sut} ===")
    runs = [score_once(cases, predict) for _ in range(args.rounds)]
    summary = summarize(runs)

    print(f"  tool_acc  {_fmt(summary['tool'])}   工具选对 / n")
    print(f"  args_acc  {_fmt(summary['args'])}   参数填对 / 工具选对   ← 条件口径")
    print(f"  both_acc  {_fmt(summary['both'])}   一次调用整体正确 / n")

    if args.sut == "fake":
        print("  fake 版只验证评测管线（分数应为 100%），不代表模型能力")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "sut": args.sut,
        "snapshot": args.snapshot,
        "cases": str(args.cases),
        "n": len(cases),
        "rounds": args.rounds,
        "tool_acc": round(summary["tool"]["mean"], 4),
        "args_acc": round(summary["args"]["mean"], 4),
        "both_acc": round(summary["both"]["mean"], 4),
        "tool_range": [round(summary["tool"]["min"], 4), round(summary["tool"]["max"], 4)],
        "args_range": [round(summary["args"]["min"], 4), round(summary["args"]["max"], 4)],
        "per_case": runs[-1]["detail"],
    }
    dest = out / f"eval_{Path(args.snapshot).name}_{args.sut}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写入 {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())