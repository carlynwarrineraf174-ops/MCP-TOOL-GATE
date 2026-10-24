# MCP Tool Gate · MCP 工具契约变更门禁

> 一句话：**别人做 MCP 工具，我做「保证工具改了之后不会悄悄弄坏调用方」的那一层。**
>
> 它回答一个具体问题：*一个按旧契约写的 Agent，在新版本的工具上还能不能跑？*
>
> 📋 **路线与验收**：见上级目录 `mcp-tool-gate-项目规划.md`（M2 补规则 → M3 评测 → M4 CI → M5 影响面归因 → M6 治理层）
> 🧭 **现在该敲什么**：见 `docs/实施手册.md`（分阶段、带命令、有完成标志——**一次只看一个阶段**）

---

## 现在能做什么（M0 + M1 已完成）

```powershell
# 1. 抓快照
python -m gate.snapshot --server examples/demo_server.py --out snapshots/v1

# 2. 把契约改坏（删参 / 收紧范围 / 改描述 / 加工具）
python examples/break_it.py

# 3. 门禁判定 —— 退出码就是 CI 卡点
python -m gate.check --base snapshots/v1 --head snapshots/v2
echo $LASTEXITCODE   # 1
```

实际输出（真实运行，非示意）：

```
base=snapshots/v1  head=snapshots/v2
worst=BREAKING  BREAKING=2  RISKY=1  SAFE=1
------------------------------------------------------------------------------
[BREAKING] query_order      prop_removed         入参 with_items 被删除
[BREAKING] search_doc       range_tightened      新增上限 maximum=5，老取值可能越界
[RISKY   ] get_weather      description_changed  工具描述变化：模型选工具的输入变了
[SAFE    ] cancel_order     tool_added           新增工具（放进评测看选择干扰）
[gate] 失败：worst=BREAKING >= 阈值=breaking
```

产物：`reports/report.md`（贴 PR 评论）、`reports/report.json`（CI artifact）。

## 三档严重度怎么来的

| 档位 | 含义 | 来源 |
|---|---|---|
| **BREAKING** | 确定的破坏性变更，老调用方会坏 | oasdiff `ERR` |
| **RISKY** | 不坏代码，但改变行为或模型选择 | oasdiff `WARN` |
| **SAFE** | 向后兼容 | oasdiff `INFO` |

完整规则表（20 条，含每条的理由）见 `gate/rules.py`，跑一次会附在 `report.md` 末尾。

## 三条设计判断（面试会追问）

1. **`$ref` 必须展开后再比** —— 只比 `"$ref": "#/$defs/Tool"` 这个字符串，会漏掉内层 `type` 的变更。
2. **`oneOf` 的顺序没有语义** —— 不归一化就会把"换了个顺序"误报成 BREAKING，而**误报一次，团队就会把门禁关掉**（这是 lab_04 跑出来的真实结局）。
3. **请求侧和响应侧方向相反** —— 入参"收紧"（删参/加 required/缩 enum）是破坏；出参"放宽"（扩 enum/删字段）才是破坏。

第四条更细：**`default` 不是兼容性保证**。加 `required` 即使带 `default` 也判 BREAKING —— `default` 是服务端兜底，不是契约。

## 为什么门禁本身不用 LLM（LangChain / LangGraph 用在哪）

**分层，不是不会用**：

| 层 | 用什么 | 为什么 |
|---|---|---|
| **判定层**（本仓库 `gate/`） | 纯确定性代码，**零依赖网络** | 跑在 CI 里，同一个 commit 必须每次结论一致；用 LLM 判"破不破坏"会出现两次跑出两个结果，这种门禁没人敢用 |
| **被测对象**（M3 `sut/agent.py`） | **LangGraph + LangChain（`langchain-mcp-adapters`）** | 评测要量的是"真 Agent 在真 schema 下选对工具的概率"，假模型算出来的是噪声 |
| **语义路由**（M6 `govern/router.py`） | 工具描述 embedding / 可选 LC 组件 | 20+ 工具时上下文膨胀，要靠召回降 token |

所以 LangChain/LangGraph 在这个项目里是**被测对象与路由**，不是判定引擎。**把 LLM 塞进 diff 是负分**——面试官会问"你为什么要用框架做字符串比较"。

## 与现有工具的差别（为什么要自己写）

| 工具 | 它做什么 | 我不做什么 / 我做什么 |
|---|---|---|
| `mcp-test-harness` | **执行**测试：断言调用结果、快照、时延 | 它测"这一次调用对不对"；我测"**改了 schema 之后，老的调用方式还对不对**" |
| FastMCP Proxy / Middleware | 转发、中间件 | 它管**运行时**流量；我管**变更时**的契约 |
| oasdiff / openapi-diff | OpenAPI 的 breaking 判定 | 规则思路照抄（45 条枚举），但**输入是 MCP 的 JSON Schema，输出是 CI 退出码** |
| deepeval `MCPUseMetric` | 评"工具选对没、参数填对没" | 它评一次调用；我评**一次变更的影响面**（下一步：漂移 → 自动重跑评测） |

## 目录

```
mcp-tool-gate/
├─ examples/demo_server.py    # 3 个工具的假 MCP Server（30 行，随时可重写）
├─ examples/break_it.py       # 把 v1 改坏成 v2（"改坏实验"产品化）
├─ gate/snapshot.py           # 连上去取 tools/list，落盘 + sha256
├─ gate/diff.py               # 心脏：$ref 展开 / oneOf 归一化 / 请求响应分向
├─ gate/rules.py              # 20 条规则表（纯数据，每条形如"为什么这么判"）
├─ gate/check.py              # CLI：报告 + 退出码
├─ tests/                     # 21 个用例（含 5 个"不该报警"的负例）
└─ snapshots/v1, v2/          # 基线快照（提交进 git，CI 才有得比）
```

## 测试

```powershell
python -m unittest discover -s tests -t .     # 21 passed
# 或装 pytest 后： pytest -q
```

**负例比正例重要**：`oneOf` 换序、范围放宽、描述相同、快照未变——这些都必须"不报警"。

## 下一步（按顺序）

- [ ] 规则表补到 20 条（`not`/`pattern`/`const`/`prefixItems`）
- [ ] `gate/eval.py`：20 个 case × 3 轮 → `tool_acc` / `args_acc` **分开报**
- [ ] 漂移 → 自动重跑评测 → 输出影响面（**这是差异化，别人不做**）
- [ ] GitHub Actions：pytest + 门禁 + 把 report 塞进 PR 评论
- [ ] 治理层（可选）：FastAPI 代理 + Redis 令牌桶 + 审计落库 + Prometheus p95

## 已知限制（写在这里，面试被问就直说）

- 目前只比 `input_schema` / `output_schema`，不比 examples 与 annotations
- 没有做"语义等价"判断（如 `string` + `format: date` 与自定义类型）
- 单机单进程，没有并发场景；性能数据要等治理层
