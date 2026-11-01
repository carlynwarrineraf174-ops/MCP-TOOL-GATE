# 🛡️ MCP Tool Gate

**给 MCP 工具做「契约门禁」：在工具 schema 变更合码前，用确定性 diff 判断它会不会破坏已有 Agent，并用评测把「破坏」翻译成业务损失。**

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB">
  <img alt="Tests" src="https://img.shields.io/badge/tests-72%20passed-brightgreen">
  <img alt="Rules" src="https://img.shields.io/badge/rules-33-blue">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-1.x-6f42c1">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

> A deterministic contract gate for MCP tools — catch breaking tool-schema changes before they silently degrade your agents, then quantify the damage with an eval harness.

> **项目状态**：v0.1，核心链路已完成（快照 → 语义 diff → CI 卡点 → 评测 → 影响面归因，外加一个可选的轻量治理层）。
> 这是一个**工具/基础设施向的个人项目**，不是生产级网关；下面「已知限制」里写清了它的边界。

---

## 📖 目录

- [为什么需要它](#-为什么需要它)
- [核心特性](#-核心特性)
- [快速开始](#-快速开始)
- [接入自己的仓库](#-接入自己的仓库)
- [设计取舍](#-设计取舍)
- [评测口径](#-评测口径)
- [实测结果](#-实测结果)
- [可选的治理层](#-可选的治理层)
- [架构](#-架构)
- [项目结构](#-项目结构)
- [测试](#-测试)
- [已知限制](#-已知限制)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 😖 为什么需要它

MCP 工具就是 Agent 的「接口」。但接口改坏了，**强类型客户端会报错，LLM Agent 不会**：

| 变更 | 强类型客户端 | LLM Agent |
|---|---|---|
| 参数 `city` 从 `string` 改成 `int` | 序列化直接报错 | **不报错**：把 `"北京"` 硬塞进去，或者干脆改选另一个工具 |
| 删掉一个可选参数 | 老调用照旧，通常无感 | **工具语义变了**：模型仍然选它，但参数不再传出（实测：`slow` 删掉唯一的 `ms` 后，5 条用例的参数全错，而工具选择率反而看不出问题） |
| 新增必填参数（哪怕带 `default`） | 缺参报错 | 模型「猜」一个值填进去 → 静默错 |

Agent 的失败是**静默**的：日志里没有异常，评测总分可能还涨了，只有少数用例悄悄从对变错。

这个项目在**合码前**加一层确定性检查，并把「契约变更」和「评测损失」连起来：

```text
工具 schema 变更 ──▶ 契约 diff（BREAKING / RISKY / SAFE）
                          │
                          ├─▶ CI 退出码 1 + PR 评论（拦住）
                          │
                          └─▶ 重跑评测 → 哪几条 case 从全对变全错？对应哪条变更？
```

---

## ✨ 核心特性

- **快照**：连任意 stdio MCP Server，把 `tools/list` 落成可 diff、可 review 的 JSON（带 `sha256` 指纹）
- **语义 diff**：33 条规则、三级严重度（BREAKING / RISKY / SAFE）；`$ref` 展开、`oneOf` 归一化、**请求侧与响应侧分向判定**
- **CI 卡点**：退出码 `1` 卡住 PR，同时产出 `report.md`（贴 PR 评论）和 `report.json`（CI artifact）
- **影响面归因**：契约漂移 → 自动重跑 LangGraph SUT → 报出「哪几条用例从对变错 + 对应哪条变更」
- **可选的治理层**：HTTP / stdio 双通道 MCP 代理 + Redis Lua 令牌桶限流 + 脱敏审计 + Prometheus 指标

---

## 🚀 快速开始

要求：Python 3.10+。门禁与评测自检零外部服务；只有真实评测需要 `DEEPSEEK_API_KEY`。

```bash
git clone https://github.com/carlynwarrineraf174-ops/MCP-TOOL-GATE.git
cd MCP-TOOL-GATE

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -e .
```

### 1. 抓一份工具快照

```bash
python -m gate.snapshot --server examples/demo_server.py --out snapshots/v1
```

```text
[ok] 3 个工具 -> snapshots/v1/tools.json  sha256=a3e6bfb837a3
     - get_weather
     - query_order
     - search_doc
```

### 2. 把契约改坏，跑门禁

```bash
python examples/break_it.py
python -m gate.check --base snapshots/v1 --head snapshots/v2
```

```text
worst=BREAKING  BREAKING=2  RISKY=1  SAFE=1
[BREAKING] query_order  prop_removed         入参 with_items 被删除
[BREAKING] search_doc   range_tightened      新增上限 maximum=5
[RISKY   ] get_weather  description_changed  工具描述变化
[SAFE    ] cancel_order tool_added           新增工具
[gate] 失败：worst=BREAKING >= 阈值=breaking
```

退出码 `1` 就是 CI 卡点；报告默认写到 `reports/report.md` / `reports/report.json`。
也可以用等价的命令 `mcp-gate --base snapshots/v1 --head snapshots/v2`。

### 3. 评测管线自检（不花钱）

```bash
python -m gate.eval --cases cases/tool_selection.json --sut fake --rounds 1
```

```text
tool_acc  100.00% [100.00%, 100.00%]   工具选对 / n
args_acc  100.00% [100.00%, 100.00%]   参数填对 / 工具选对
both_acc  100.00% [100.00%, 100.00%]   一次调用整体正确 / n
```

`--sut fake` 只验证评测管线：它跌破 100%，说明坏的是管线而不是模型。

### 4. 真实评测 + 影响面归因（可选）

```bash
# 需要 DEEPSEEK_API_KEY（参考 .env.example）
python -m gate.eval   --cases cases/tool_selection.json --sut real --rounds 3 --snapshot snapshots/real-v1
python -m gate.impact --base snapshots/real-v1 --head snapshots/real-v2
```

### 5. 治理层（可选，需要 Docker）

```bash
pip install -e ".[govern]"
docker compose up -d --build        # 8000 = Prometheus，8001 = MCP
python test_http_client.py          # 握手 + 拉工具 + 验证 structuredContent
curl http://127.0.0.1:8000/metrics
```

> Windows PowerShell 下环境变量写法不同，例如：`$env:GOVERN_RATELIMIT_ENABLED="true"; python govern/proxy.py`。

---

## 🔁 接入自己的仓库

把「抓当前契约 → 与基线比对」放进 CI：

```yaml
- name: 抓当前契约
  run: python -m gate.snapshot --server <你的 MCP server> --out snapshots/current

- name: 契约门禁
  run: python -m gate.check --base snapshots/baseline --head snapshots/current
  # exit 1 = 有 BREAKING → PR 变红
```

退出码语义：

| 退出码 | 含义 |
|---|---|
| `0` | 通过 |
| `1` | 达到阈值（默认 `breaking`；`--fail-on risky` 可收紧） |
| `2` | 快照缺失或参数错误 |

建议先把基线快照 `baseline` 提交进仓库，之后每次 PR 抓一份 `current` 比对——这样契约变更会出现在 diff 里，和代码一样被 review。

---

## 🧠 设计取舍

1. **`$ref` 必须展开后再比** —— 只比 `"$ref": "#/$defs/Tool"` 这个字符串，会漏掉内层 `type` 的变更。
2. **`oneOf` 的顺序没有语义** —— 不归一化会把「换个顺序」误报成 BREAKING；而**误报一次，团队就会把门禁关掉**。
3. **请求侧和响应侧方向相反** —— 入参「收紧」（删参 / 加 required / 缩 enum）是破坏；出参「放宽」（扩 enum / 删字段 / 删 const）才是破坏。
4. **没写 `enum` / `type` / `items` 等于「不限」** —— 所以「从无到有」恰恰是收紧。第一版只比了「两边都存在」的键，真实靶场注入 6 处只检出 5 处（`boom.reason` 新增 enum 被静默放过）；修完才是 **6/6**。
5. **`default` 不是兼容性保证** —— 新增 `required` 即使带默认值也判 BREAKING：`default` 是服务端兜底，不是契约。

**为什么判定层不用 LLM**：门禁跑在 CI 里，同一个 commit 必须每次结论一致、零网络、零成本。用 LLM 判「破不破坏」会出现两次跑出两个结果——这种门禁没人敢用。**LLM 只出现在被测对象（SUT）里。**

---

## 📊 评测口径

| 指标 | 定义 | 什么时候看它 |
|---|---|---|
| `tool_acc` | 工具选对 / n | 选错工具 = 没理解意图 → 改工具 description |
| `args_acc` | 参数填对 / **工具选对**（条件口径） | 分母不是 n：工具都选错时「参数恰好对」是运气 |
| `both_acc` | 一次调用整体正确 / n | 端到端可用率 |

每条 case × **3 轮**（当前 30 条：20 条基础 + 10 条「一句话同时沾两个工具」的歧义用例），报 `mean [min, max]`：**单轮噪声约 ±8pp，比要检测的退化还大**，所以不看单轮数字。

---

## 🏆 实测结果

一次 30 条 case × 3 轮的本地评测（LangGraph SUT，`--sut real`）：

```text
=== 影响面归因报告 ===
基准版本: real-v1 | 对比版本: real-v2
工具选择准确率: 87.78% -> 95.56% (Δ +7.78 pp)
参数填写准确率: 92.40% -> 75.57% (Δ -16.83 pp)
受影响的具体用例: c07, c12, c20, c24, c28
对应变更原因: slow.prop_removed (BREAKING)
```

读法：**删掉 `slow.ms` 这唯一的入参，参数准确率掉 16.83 个点，5 条用例从「每轮全对」变成「每轮都错」**。这 5 条**全都还把 `slow` 选对了**，只是没地方填「500 毫秒」——`both_acc` 从 81.11% 掉到 72.22%。

`tool_acc` 反而 **+7.78pp**：单轮噪声约 ±8pp，同一份契约重跑也会漂，这个数不能当提升（工具集里还多了 `health_check` 干扰项）。**这正是「只看总分会被骗」的证据**，也是为什么三个分数要分开报。

> 数字由上面的 `gate.eval` + `gate.impact` 命令在本地复现；LLM 采样有噪声，换机器/换模型会漂。

### 门禁在 CI 里的样子

![CI 机器人把契约变更报告贴回 PR](docs/images/ci-gate-failed2.png)

![门禁失败](docs/images/ci-gate-failed.png)

![门禁通过](docs/images/ci-gate-success.png)

> 截图拍摄时仓库里是 42 个用例，当前为 72 个。

---

## 🛡️ 可选的治理层

除了「合码前」的门禁，仓库里还有一层可选的运行期代理（`govern/`）：它不做业务，只把调用管起来。

```text
Agent ──MCP(HTTP :8001/mcp 或 stdio)──▶ govern/proxy.py
                                          ├─ ① 令牌桶限流（Redis + Lua，原子扣减）
                                          ├─ ② 脱敏审计（只存 args_keys + sha256）
                                          ├─ ③ Prometheus 指标（:8000/metrics）
                                          └─ ④ 原样转发 ──stdio──▶ 上游 MCP Server
```

| 能力 | 实现 | 验证方式 |
|---|---|---|
| 原样透传 | lowlevel `Server`：`list_tools` 直接返回上游 `Tool`，`call_tool` 直接返回上游 `CallToolResult`（`content` 与 `structuredContent` 都不改写） | rich 靶场直连 / 过代理快照逐字节相等；带 `outputSchema` 的工具 `structuredContent` 非空 |
| 双通道 | 默认 HTTP（`streamable-http`，`:8001/mcp`）；`--transport stdio` 给 bench / snapshot 用 | `python test_http_client.py` |
| 限流 | Redis Lua 令牌桶，`burst / rate / interval` 可配；Redis 异常按 `fail-open` / `fail-closed` 降级 | 开限流后 8 并发 → 5 过 3 拒；两个租户互不影响 |
| 审计 | `asyncio.create_task` 异步落库 + `asyncio.Lock` 串行化，只存参数 key 列表与 sha256 | `select * from tool_audit` 看不到明文 |
| 停机 | `SIGTERM` / `Ctrl+C` 时 `drain()` 等待后台审计任务落库 | 8 请求 → 停止 → 查库 8 条 |

常用环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `GOVERN_UPSTREAM_ARGS` | `["examples/demo_server_rich.py"]` | 上游启动参数，**JSON 数组** |
| `GOVERN_HTTP_PORT` | `8001` | MCP HTTP 端口 |
| `GOVERN_METRICS_PORT` | `8000` | Prometheus 端口，`0` 表示关闭 |
| `GOVERN_REDIS_URL` | `redis://localhost:6379/0` | 限流用 Redis |
| `GOVERN_RATELIMIT_ENABLED` | `false` | 限流开关 |
| `GOVERN_DB_URL` | `sqlite+aiosqlite:///./govern.db` | 审计库 |
| `GOVERN_TENANT_ID` | `default_tenant` | stdio 模式下的租户 ID（HTTP 用 `X-Tenant-Id` 头） |

---

## 🧩 架构

门禁（合码前）：

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

治理层（运行期，可选）：

```text
 Agent ──MCP(HTTP / stdio)──▶ govern/proxy.py ──┬─ 限流（Redis Lua 令牌桶）
                                                 ├─ 审计（脱敏 → SQLite）
                                                 ├─ 指标（:8000/metrics）
                                                 └─ 转发 ──stdio──▶ 上游 MCP Server
```

---

## 📁 项目结构

```text
mcp-tool-gate/
├─ gate/
│  ├─ snapshot.py        # 连 MCP Server 取 tools/list，落盘 + sha256
│  ├─ diff.py            # 心脏：$ref 展开 / oneOf 归一化 / 请求响应分向
│  ├─ rules.py           # 33 条规则表（纯数据，每条带「为什么这么判」）
│  ├─ check.py           # CLI：报告 + 退出码
│  ├─ eval.py            # 评测：三分数 + 多轮区间（条件口径）
│  └─ impact.py          # 漂移 → 受损 case → 对应 finding
├─ govern/               # 可选治理层：代理 / 限流 / 审计 / 指标
├─ sut/agent.py          # 被测对象：手搭的 LangGraph 图（StateGraph + ToolNode）
├─ cases/                # 30 条 case（20 基础 + 10 歧义）+ fake 答案表
├─ examples/             # demo server / rich 靶场 / 改坏脚本
├─ snapshots/            # v1·v2、real-v1·real-v2、rich-direct·rich-via-proxy
├─ tests/                # 72 个用例：diff / check / eval / impact / rules / govern e2e
├─ bench/bench.py        # 直连 vs 过代理的 p95 对照（stdio）
├─ Dockerfile / docker-compose.yml
├─ alembic/              # 审计表迁移（当前为占位）
└─ docs/images/          # CI 截图
```

---

## 🧪 测试

```bash
python -m unittest discover -s tests -t .
# Ran 72 tests ... OK
```

**负例比正例重要**：`oneOf` 换序、范围放宽、`title` 改名、快照未变、`nullable` 放宽、去掉 `enum`、输出 schema 换个等价写法（`allOf` 包一层 / 单元素 `type` 数组）——这些都必须「不报警」。门禁误报一次，团队就会把它关掉。

测试覆盖三层：

- **判定层**：每条规则的正例 + 负例，以及「归一化不能吞掉真变更」的元测试
- **CLI 层**：`gate.check` 的退出码（0 / 1 / 2）与报告产物
- **治理层**：rich 靶场直连 vs 过代理的 schema 逐字节相等；HTTP 端到端（空闲端口 + 临时 DB）；规则表一致性

---

## ⚠️ 已知限制

- 评测只有 **30 条 case、工具池 4 个**（add/echo/boom/slow），工具选择难度低于真实场景（20+ 工具、描述高度相似）
- 语义等价只做到「**写法级**」：`allOf` 包一层、单元素 `type` 数组、空 `required`、元数据变化不会误报；但 `format` 的等价（`date` vs `date-time`）和自定义类型仍转人工
- 分数会抖：`--rounds 3` 只能把标准误压到约一半，**±5pp 以内的差异不要当成提升或退化**
- 只比较 `input_schema` / `output_schema`，不比 `examples` / `annotations`
- 治理层只覆盖 `tools/list` 与 `tools/call`，`resources` / `prompts` 未覆盖；没有鉴权与多租户认证，只有 `X-Tenant-Id` 识别
- 审计用单机 SQLite；`alembic/` 迁移是占位，建表在启动时完成
- 没有生产级压测数据；`bench.py` 是单条 stdio 连接的对照，测的是排队而不是并发
- 镜像是开发用的，没有做多阶段构建与瘦身

---

## 🗺️ Roadmap

- [ ] CI 里抓真实 `tools/list` 再比对 baseline（现在演示用的是仓库内固定快照）
- [ ] 429 / JSON-RPC 结构化错误（治理层）、Alembic 真实迁移
- [ ] 评测扩容：工具池 4 → 20、case 30 → 100、固定随机种子
- [ ] 治理层鉴权与多租户身份（OIDC / mTLS）
- [ ] HTTP 多连接压测，给出 QPS / p95 数据
- [ ] `format` 与自定义类型的语义等价

---

## 🤝 贡献

Issue / PR 都欢迎。提交前请确保：

```bash
python -m unittest discover -s tests -t .
```

新增判定规则时，请同时补 **正例 + 负例**（不报警的用例），并在 `gate/rules.py` 里写清「为什么这么判」。

---

## 📄 License

[MIT](LICENSE) © 2026 carlynwarrineraf174

---

## 🙏 参考与致谢

- 严重度分档思路来自 [oasdiff](https://github.com/tufin/oasdiff)
- 兼容性规则骨架参考 [openapi-diff](https://github.com/OpenAPITools/openapi-diff) 的 incompatible 枚举
- MCP 协议与客户端来自官方 [python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- 评测口径（三分数分离、多轮采样）参考 [deepeval](https://github.com/confident-ai/deepeval) 的 `MCPUseMetric`
