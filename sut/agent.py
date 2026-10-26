"""真实的 LangGraph Agent 作为被测对象（SUT）。"""
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

# 假设你已经在环境变量里配了 DEEPSEEK_API_KEY
# 如果没配，可以直接把 api_key 写死在下面（测试用）
load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


# 初始化模型，记得关闭思考模式（DeepSeek 的老坑）
llm = ChatOpenAI(
    model="deepseek-flash",
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
    extra_body={"thinking": {"type": "disabled"}}
)


def run_real_agent(query: str, snapshot_dir: str = "snapshots/real-v1") -> dict:
    """读取指定快照里的工具，让真实模型决策。"""
    tools_path = Path(snapshot_dir) / "tools.json"
    tools_data = json.loads(tools_path.read_text(encoding="utf-8"))

    # 把快照里的工具格式，转成大模型 API 需要的格式
    openai_tools = []
    for name, info in tools_data.items():
        openai_tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info.get("description", ""),
                "parameters": info.get("input_schema", {})
            }
        })

    # 绑定工具并调用
    llm_with_tools = llm.bind_tools(openai_tools)
    messages = [
        SystemMessage(content="你是一个智能助手，请根据用户问题调用最合适的工具。"),
        HumanMessage(content=query)
    ]

    response = llm_with_tools.invoke(messages)

    # 从响应里提取模型选择了什么工具
    if not response.tool_calls:
        return {"tool": "unknown", "args": {}}

    # 我们只取第一个工具调用（真实业务里可能会有多个）
    first_call = response.tool_calls[0]
    return {
        "tool": first_call["name"],
        "args": first_call["args"]
    }