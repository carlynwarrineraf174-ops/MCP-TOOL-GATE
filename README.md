# 🛡️ MCP Tool Gate · AI 工具契约质量门禁

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-42%20passed-brightgreen)
![Rules](https://img.shields.io/badge/rules-31-blue)
![CI](https://img.shields.io/badge/CI-gate%20enforced-orange)

> **别人做 Agent 应用，我做「保证 Agent 不会因为工具契约变更而悄悄变笨」的那一层。**
>
> 它回答一个具体问题：**一个按旧契约写的 Agent，在新版本的工具上还能不能跑？**

## 😖 为什么需要它

MCP 工具就是 Agent 的"接口"。但接口改坏了，**强类型客户端会报错，LLM Agent 不会**：

| 变更 | 强类型客户端 | LLM Agent |
|---|---|---|
| 参数 `city` 从 `string` 改成 `int` | 序列化直接报错 | **不报错**：把 `"北京"` 硬塞进去，或者干脆改选另一个工具 |
| 删掉一个可选参数 | 老调用照旧，通常无感 | **工具语义变了**：模型重新理解它是干什么的（实测：`slow` 删掉 `ms` 后，它去调了 `health_check`） |
| 新增必填参数（哪怕带 `default`） | 缺参报错 | 模型"猜"一个值填进去 → 静默错 |

所以 Agent 的失败是**静默**的，排查成本极高；必须有一层在**合码前**拦住契约变更。这就是本项目。

## ✅ 它做什么

- **快照**：连任意 stdio MCP Server，把 `tools/list` 落成可 diff 的 JSON（带 `sha256`）
- **语义 diff**：31 条规则 / 三级严重度（BREAKING · RISKY · SAFE）；`$ref` 展开、`oneOf` 归一化、**请求侧与响应侧分向判定**
- **CI 卡点**：退出码 1 卡住 PR + `report.md`（贴 PR 评论）/ `report.json`（CI artifact）
- **影响面归因**：漂移 → 自动重跑评测（LangGraph SUT）→ 报出「哪几条用例从对变错、对应哪条变更」

## 🎬 真实场景（截图都来自本仓库的 GitHub Actions）

**① 一个普通 PR：把 `city` 从 `string` 改成 `int`**

![CI 机器人把契约变更报告贴回 PR，PR 被卡住](docs/images/ci-gate-failed2.png)

机器人自动贴出「BREAKING 1 条 / RISKY 1 条 + 明细表 + 规则目录」，PR 变红。**人不用去读日志。**

**② 测试绿 ≠ 门禁绿**

| 门禁红（有 BREAKING） | 门禁绿（只有 RISKY） |
|---|---|
| ![gate failed](docs/images/ci-gate-failed.png) | ![gate success](docs/images/ci-gate-success.png) |
| `42 tests OK`，但第 6 步 `exit 1` | `worst=RISKY  BREAKING=0` → `[gate] 通过` |

**测试证明「代码没坏」，门禁证明「契约没坏」—— 两种红是两件事。**

**③ 改参数 → 门禁卡住**

![改入参后门禁卡住](docs/images/ci-gate-failed1.png)

## 🚀 核心战绩：从静态拦截到影响面归因

静态规则能告诉你"这里有破坏性变更"，但说不清**影响多大**。本项目用真实的 LangGraph Agent 跑评测，把变更翻译成业务损失：

```text
=== 影响面归因报告 ===
基准版本: snapshots/real-v1 | 对比版本: snapshots/real-v2
工具选择准确率: 98.33% -> 98.33% (Δ +0.00 pp)
参数填写准确率: 89.82% -> 76.32% (Δ -13.50 pp)

⚠️ 受影响的具体用例: c07, c12, c20
🔍 对应变更原因: slow.prop_removed (BREAKING)
```

一句话读法：**删掉 `slow.ms` 这一个参数，参数准确率掉 13.5 个点，3 条用例从对变错** —— 而且其中 1 条是直接**选错了工具**（`slow` → `health_check`）：`ms` 没了，模型就重新理解了 `slow` 的用途。

## ⚡ 快速开始

需要 Python 3.10+；三条命令零外部服务，评测另外需要 `DEEPSEEK_API_KEY`。

```powershell
pip install -e .            # 或 uv sync

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

## 🧠 判定引擎：五条设计判断（面试会追问）

1. **`$ref` 必须展开后再比** —— 只比 `"$ref": "#/$defs/Tool"` 这个字符串，会漏掉内层 `type` 的变更。
2. **`oneOf` 的顺序没有语义** —— 不归一化就会把"换个顺序"误报成 BREAKING；而**误报一次，团队就会把门禁关掉**。
3. **请求侧和响应侧方向相反** —— 入参"收紧"（删参 / 加 required / 缩 enum）是破坏；出参"放宽"（扩 enum / 删字段）才是破坏。
4. **没写 `enum` / `type` / `items` 等于"不限"** —— 所以"从无到有"恰恰是收紧。第一版只比了"两边都存在"的键，真实靶场注入 6 处只检出 5 处（`boom.reason` 新增 enum 被静默放过）；修完才是 **6/6**。
5. **`default` 不是兼容性保证** —— 新增 `required` 即使带默认值也判 BREAKING：`default` 是服务端兜底，不是契约。

> 为什么判定层**不用 LLM**：门禁跑在 CI 里，同一个 commit 必须每次结论一致、零网络、零成本。
> 用 LLM 判"破不破坏"会出现两次跑出两个结果——这种门禁没人敢用。**LLM 只出现在被测对象（SUT）里。**

## 📊 评测口径：三个分数，不是一个

| 指标 | 定义 | 什么时候看它 |
|---|---|---|
| `tool_acc` | 工具选对 / n | 选错工具 = 没理解意图 → 改工具 description |
| `args_acc` | 参数填对 / **工具选对**（条件口径） | 分母不是 n：工具都选错时"参数恰好对"是运气 |
| `both_acc` | 一次调用整体正确 / n | 端到端可用率 |

20 条 case × **3 轮**，报 `mean [min, max]`：**单轮噪声约 ±8pp，比要检测的退化还大**，所以不看单轮数字。
`--sut fake` 只做管线自检；`--sut real` 才是真分数（LangGraph SUT，代码在 `sut/agent.py`）。

## 🧩 架构

```text
 MCP Server ──tools/list──▶ gate.snapshot ──▶ snapshots/<name>/tools.json  (提交进 git，可 review)
                                                     │
 PR 改了工具 ──tools/list──▶ gate.snapshot ──────────┤
                                                     ▼
                                          gate.diff + gate.rules（纯确定性，零网络）
                                                     │
                          ┌──────────────────────────┼──────────────────────────┐
                          ▼                          ▼                          ▼
                 reports/report.md           退出码 1（CI 卡点）        gate.eval（LangGraph SUT）
                 reports/report.json                                     │ 三分数 × 3 轮
                                                                         ▼
                                                                 gate.impact（Δ + 受损 case + 原因）
```

## 📁 目录结构

```text
mcp-tool-gate/
├─ gate/snapshot.py       # 连 MCP Server 取 tools/list，落盘 + sha256
├─ gate/diff.py           # 心脏：$ref 展开 / oneOf 归一化 / 请求响应分向
├─ gate/rules.py          # 31 条规则表（纯数据，每条带"为什么这么判"）
├─ gate/check.py          # CLI：报告 + 退出码
├─ gate/eval.py           # 评测：三分数 + 多轮区间（条件口径）
├─ gate/impact.py         # 漂移 → 受损 case → 对应 finding
├─ sut/agent.py           # 被测对象：手搭的 LangGraph 图（StateGraph + ToolNode）
├─ cases/                 # 20 条 case + fake 答案表（管线自检基线）
├─ examples/              # demo server / 改坏脚本 / 真实靶场注入
├─ snapshots/             # v1·v2（假靶场）、real-v1·real-v2（真实靶场）
├─ tests/                 # 42 个用例，负例优先
└─ docs/                  # 实施手册、修复手册、CI 截图
```

## 🧪 测试

```powershell
python -m unittest discover -s tests -t .     # 42 passed
```

**负例比正例重要**：`oneOf` 换序、范围放宽、`title` 改名、快照未变、`nullable` 放宽、去掉 `enum` —— 这些都必须"不报警"。门禁误报一次，团队就会把它关掉。

## 🔁 接入你自己的仓库

```yaml
- name: 契约门禁
  run: python -m gate.check --base snapshots/baseline --head snapshots/current
  # exit 1 = 有 BREAKING → PR 变红
```

退出码语义：`0` 通过 / `1` 达到阈值 / `2` 快照缺失或参数错误。
阈值可调：`--fail-on risky` 会把 RISKY（如描述变更）也算作失败 —— 建议先只卡 `breaking`，等团队信任了再收紧。

## ⚠️ 已知限制与取舍（被问到就直说）

- `per_case` 存的是**最后一轮**明细，而分数是 3 轮均值 —— 两个口径不同，case 级结论要按"多轮都坏才算受损"重算
- `impact.py` 不校验 `report.json` 与本次 eval 是否同一对版本，混跑会把原因安错
- 评测 20 条 case 只覆盖 4 个工具，缺"近义工具干扰"那一类 → `tool_acc` 的上限被抬高
- 只比 `input_schema` / `output_schema`，不比 examples / annotations，也不做语义等价（`format: date` vs 自定义类型）
- **没有做治理层**（代理 / 限流 / 审计 / 指标）：FastMCP 4 已内置 Proxy / Middleware / Auth，重写一遍是**负分**；限流与压测我放在另一个「单体高并发」项目里做

## 🗺️ 下一步

- [ ] `per_case` 改成多轮聚合率（口径统一）
- [ ] `impact.py` 加版本一致性断言
- [ ] case 补到 30 条，加入"近义工具干扰"
- [ ] 支持 `outputSchema` 的语义等价判定

## 🙏 参考与致谢

判定规则的思路来自 [oasdiff](https://github.com/tufin/oasdiff)（三档严重度）与 [openapi-diff](https://github.com/OpenAPITools/openapi-diff)（45 条 incompatible 枚举）；
MCP 协议与客户端来自官方 [python-sdk](https://github.com/modelcontextprotocol/python-sdk)；
评测口径（三分数分离、多轮采样）参考 [deepeval](https://github.com/confident-ai/deepeval) 的 `MCPUseMetric` 与读数实验。
