"""sut/agent.py —— 被测对象（SUT）：手搭的 LangGraph 图，工具来自快照。

为什么是「快照驱动」而不是连真 server：
    评测要可复现 —— 同一份 tools.json 每次跑出来的工具集完全一致，
    否则"准确率变了"分不清是模型漂移还是工具集变了。

图长这样（两个节点 + 一条条件边）：
    agent ──(有 tool_calls)──> tools ──┐
      ^                                │
      └────────────────────────────────┘
    agent ──(无 tool_calls)──> END

评测时默认 truncate=True：一出现 tool_calls 就结束，不真执行工具 ——
因为我们只量"选了哪个工具、填了什么参数"，省掉一半模型调用。

API Key 只从环境变量读（不进仓库）：
    .env 里放 DEEPSEEK_API_KEY=...   或   系统环境变量里设置
"""

import json
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import create_model

load_dotenv()   # 本地有 .env 就用；没有也不报错（可能走系统环境变量）

_LLM_CACHE: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    """懒加载模型：import 这个模块不需要 key，只有真跑评测时才检查。"""
    global _LLM_CACHE
    if _LLM_CACHE is not None:
        return _LLM_CACHE

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未设置。二选一：\n"
            "  1) 复制 .env.example 为 .env，填入你的 key（.env 已被 .gitignore 忽略）\n"
            "  2) 设置系统环境变量 DEEPSEEK_API_KEY 后重开终端"
        )

    _LLM_CACHE = ChatOpenAI(
        model="deepseek-flash",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        extra_body={"thinking": {"type": "disabled"}},   # DeepSeek 带 tools 必须关思考
    )
    return _LLM_CACHE


class AgentState(TypedDict):
    # add_messages：新消息追加，不是覆盖
    messages: Annotated[list, add_messages]


def _lc_tools(tools: dict) -> list[StructuredTool]:
    """快照里的 JSON Schema → LangChain Tool。

    函数体只回 "ok"：评测只关心「模型想调哪个工具、参数是什么」，
    真执行会引入网络/数据库等不确定因素，让分数不可复现。
    """
    out: list[StructuredTool] = []
    for name, info in tools.items():
        schema = info.get("input_schema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        fields: dict[str, tuple[type, Any]] = {}
        for key in props:
            fields[key] = (Any, ... if key in required else None)
        args_model = create_model(f"{name}_args", **fields) if fields else None

        out.append(StructuredTool.from_function(
            func=lambda **_: "ok",      # stub：不真执行
            name=name,
            description=info.get("description") or "",
            args_schema=args_model,
        ))
    return out


def run_real_agent(query: str, snapshot_dir: str = "snapshots/real-v1",
                   truncate: bool = True) -> dict:
    """跑一张图，返回 {"tool": 第一个被选中的工具名, "args": 它的参数}。

    truncate=True （默认）：一出现 tool_calls 就结束，不执行工具 → 每题 1 次模型调用；
    truncate=False        ：走完整循环（agent → tools → agent）→ 每题 2 次，适合演示真 ReAct。
    """
    tools_data = json.loads((Path(snapshot_dir) / "tools.json").read_text(encoding="utf-8"))
    tools = _lc_tools(tools_data)
    llm_with_tools = _get_llm().bind_tools(tools)

    def call_model(state: AgentState):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    def should_continue(state: AgentState):
        if not state["messages"][-1].tool_calls:
            return END
        return END if truncate else "tools"

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))      # truncate=False 时才走得到
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")
    graph = workflow.compile()

    messages = [
        SystemMessage(content="你是一个智能助手，请根据用户问题调用最合适的工具。"),
        HumanMessage(content=query),
    ]
    result = graph.invoke({"messages": messages})

    for msg in reversed(result["messages"]):
        calls = getattr(msg, "tool_calls", None)
        if calls:
            first = calls[0]
            return {"tool": first["name"], "args": first.get("args") or {}}
    return {"tool": "unknown", "args": {}}
