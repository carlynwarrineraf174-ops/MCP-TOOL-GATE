# 🛡️ MCP Tool Gate · AI 工具契约质量门禁

> **一句话介绍**：别人做 Agent 应用，我做「保证 Agent 不会因为工具契约变更而悄悄崩溃」的基础设施。
> 
> 它回答一个具体问题：*一个按旧契约写的 Agent，在新版本的工具上还能不能跑？*

---

## 🚀 核心战绩：从静态拦截到 AI 影响面归因

本门禁不仅能在 CI 阶段用 31 条静态规则拦截破坏性变更，还能通过真实的 LangGraph 评测流，**量化变更带来的业务损失**。

当开发者修改了 MCP 工具（如删除了一个参数），传统的接口测试往往无法察觉，但这会导致 LLM Agent 在处理特定指令时直接崩塌。本工具能精准制导：

```text
=== 影响面归因报告 ===
基准版本: snapshots/real-v1 | 对比版本: snapshots/real-v2
工具选择准确率: 98.33% -> 98.33% (Δ +0.00 pp)
参数填写准确率: 89.82% -> 76.32% (Δ -13.50 pp)

⚠️ 受影响的具体用例: c07, c12, c20
🔍 对应变更原因: slow.prop_removed (BREAKING)
```

---

## 🚦 CI 卡点：测试红 ≠ 门禁红

![gate-check 在 GitHub Actions 里被门禁卡住](docs/images/ci-gate-failed.png)

这次 `gate-check` 里**前 5 步全绿**（设环境 / 装依赖 15s / **42 个单测全过**），只有第 6 步「跑契约门禁」是红的：`Process completed with exit code 1`。

**测试证明「代码没坏」，门禁证明「契约没坏」** —— 两种红是两件事：

```text
worst=BREAKING  BREAKING=2  RISKY=1  SAFE=1
[BREAKING] query_order   prop_removed     入参 with_items 被删除
[BREAKING] search_doc    range_tightened  新增上限 maximum=5，老取值可能越界
[gate] 失败：worst=BREAKING >= 阈值=breaking      → 退出码 1 → PR 被卡住
```

团队不用读日志：人看 `reports/report.md`（4 行明细），机器读 `reports/report.json`。

## ⚡ 快速开始（四条命令，零外部服务）

```powershell
# 1) 抓快照：连 MCP Server 的 tools/list，落盘 + sha256
python -m gate.snapshot --server examples/demo_server.py --out snapshots/v1

# 2) 把契约改坏，生成 v2（删参 / 收紧范围 / 改描述 / 加工具）
python examples/break_it.py

# 3) 门禁判定：退出码就是 CI 卡点
python -m gate.check --base snapshots/v1 --head snapshots/v2     # exit 1

# 4) 评测 + 影响面归因（需要 DEEPSEEK_API_KEY，见 .env.example）
python -m gate.eval   --cases cases/tool_selection.json --sut real --rounds 3 --snapshot snapshots/real-v1
python -m gate.impact --base snapshots/real-v1 --head snapshots/real-v2
```

`--sut fake` 是**管线自检**（读 `cases/fake_answers.json`，应恒为 100%）：不花钱，也不代表模型能力；它一跌破 100%，说明坏的是评测管线而不是模型。

## 📐 四条设计判断（面试会追问）

1. **`$ref` 必须展开后再比** —— 只比 `"$ref": "#/$defs/Tool"` 这个字符串，会漏掉内层 `type` 的变更。
2. **`oneOf` 的顺序没有语义** —— 不归一化就会把"换个顺序"误报成 BREAKING；而**误报一次，团队就会把门禁关掉**（`_labs/lab_04` 跑出来的真实结局）。
3. **请求侧和响应侧方向相反** —— 入参"收紧"（删参 / 加 required / 缩 enum）是破坏；出参"放宽"（扩 enum / 删字段）才是破坏。
4. **没写 `enum` / `type` / `items` 等于"不限"** —— 所以"从无到有"恰恰是收紧。第一版只比了"两边都存在"的键，靶场注入 6 处只检出 5 处（`boom.reason` 新增 enum 被静默放过），修完才是 6/6。
   附带一条更细的：**`default` 不是兼容性保证** —— 加 `required` 即使带默认值也判 BREAKING。

## ⚠️ 已知限制（被问到就直说）

- `per_case` 存的是**最后一轮**的明细，而分数是 3 轮均值 —— 两个口径不同；case 级结论要按"三轮都坏才算受损"重算（待办）
- `impact.py` 不校验 `report.json` 与本次 eval 是否同一对版本，混跑会把原因安错（待加断言）
- 评测 20 条 case 只覆盖 4 个工具，缺"近义工具干扰"那一类 → `tool_acc` 的上限被抬高
- 只比 `input_schema` / `output_schema`，不比 examples / annotations，也不做语义等价（`format: date` vs 自定义类型）
- 单机单进程，没有并发与压测数据；治理层（代理 / 限流 / 审计 / 指标）未做
