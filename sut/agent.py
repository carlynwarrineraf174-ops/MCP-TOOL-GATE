# """真实的 LangGraph Agent 作为被测对象（SUT）。"""
# import os
# import json
# from pathlib import Path
#
# from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
# from langchain_core.messages import HumanMessage, SystemMessage
#
# # 假设你已经在环境变量里配了 DEEPSEEK_API_KEY
# # 如果没配，可以直接把 api_key 写死在下面（测试用）
# load_dotenv()
#
# API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
#
#
# # 初始化模型，记得关闭思考模式（DeepSeek 的老坑）
# llm = ChatOpenAI(
#     model="deepseek-flash",
#     api_key=API_KEY,
#     base_url="https://api.deepseek.com",
#     extra_body={"thinking": {"type": "disabled"}}
# )
#
#
# def run_real_agent(query: str, snapshot_dir: str = "snapshots/real-v1") -> dict:
#     """读取指定快照里的工具，让真实模型决策。"""
#     tools_path = Path(snapshot_dir) / "tools.json"
#     tools_data = json.loads(tools_path.read_text(encoding="utf-8"))
#
#     # 把快照里的工具格式，转成大模型 API 需要的格式
#     openai_tools = []
#     for name, info in tools_data.items():
#         openai_tools.append({
#             "type": "function",
#             "function": {
#                 "name": name,
#                 "description": info.get("description", ""),
#                 "parameters": info.get("input_schema", {})
#             }
#         })
#
#     # 绑定工具并调用
#     llm_with_tools = llm.bind_tools(openai_tools)
#     messages = [
#         SystemMessage(content="你是一个智能助手，请根据用户问题调用最合适的工具。"),
#         HumanMessage(content=query)
#     ]
#
#     response = llm_with_tools.invoke(messages)
#
#     # 从响应里提取模型选择了什么工具
#     if not response.tool_calls:
#         return {"tool": "unknown", "args": {}}
#
#     # 我们只取第一个工具调用（真实业务里可能会有多个）
#     first_call = response.tool_calls[0]
#     return {
#         "tool": first_call["name"],
#         "args": first_call["args"]
#     }
"""sut/agent.py —— 纯手工 LangGraph SUT（快照驱动）。"""
import json
import os
from pathlib import Path
from typing import Any, Dict, TypedDict
from typing import Annotated
from langgraph.graph.message import add_messages

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from pydantic import create_model

load_dotenv()

_LLM = ChatOpenAI(
    model="deepseek-flash",
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com",
    extra_body={"thinking": {"type": "disabled"}},  # DeepSeek 带 tools 必须关思考
)

#信息覆盖
# class AgentState(TypedDict):
#     messages: list

# 1. 定义 LangGraph 的状态 (State)
class AgentState(TypedDict):
    # 加上 Annotated 和 add_messages，告诉图：新消息要追加
    messages: Annotated[list, add_messages]


def _lc_tools(tools: dict) -> list[StructuredTool]:
    """快照里的 JSON Schema → LangChain Tool。"""
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
            func=lambda **_: "ok",  # stub：不真执行
            name=name,
            description=info.get("description") or "",
            args_schema=args_model,
        ))
    return out


def run_real_agent(query: str, snapshot_dir: str = "snapshots/real-v1") -> dict:
    tools_data = json.loads((Path(snapshot_dir) / "tools.json").read_text(encoding="utf-8"))
    tools = _lc_tools(tools_data)

    # 让大模型绑定工具
    llm_with_tools = _LLM.bind_tools(tools)

    # 2. 定义节点：LLM 思考节点
    def call_model(state: AgentState):
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    # 3. 定义节点：工具执行节点 (LangGraph 预封装)
    tool_node = ToolNode(tools)

    # 4. 定义路由逻辑：判断是否要继续调用工具
    def should_continue(state: AgentState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    # 5. 构建图 (Graph)
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    # 设置入口和边
    workflow.set_entry_point("agent")

    # 条件边：从 agent 出来后，交给 should_continue 决定去哪
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )

    # 循环边：工具执行完后，回到 agent 继续思考
    workflow.add_edge("tools", "agent")

    # 6. 编译并运行
    app = workflow.compile()

    # 初始消息：给模型加个系统提示，告诉它选工具
    messages = [
        SystemMessage(content="你是一个智能助手，请根据用户问题调用最合适的工具。"),
        HumanMessage(content=query)
    ]

    result = app.invoke({"messages": messages})

    # 7. 从结果里提取第一个工具调用
    for msg in reversed(result["messages"]):
        calls = getattr(msg, "tool_calls", None)
        if calls:
            first = calls[0]
            return {"tool": first["name"], "args": first.get("args") or {}}
    return {"tool": "unknown", "args": {}}