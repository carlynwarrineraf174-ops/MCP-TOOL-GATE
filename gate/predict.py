def predict(query: str) -> dict:
    """假模型：按关键词瞎蒙。"""
    if "天气" in query:
        return {"tool": "get_weather", "args": {"city": "北京"}}
    if "订单" in query:
        return {"tool": "query_order", "args": {"order_id": "123"}}
    if "搜" in query or "文档" in query:
        return {"tool": "search_doc", "args": {"query": "文档"}}

    return {"tool": "unknown", "args": {}}