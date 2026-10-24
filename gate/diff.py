"""schema 语义 diff —— 这个项目的"心脏"。

它只回答一个问题：
    一个按旧契约写的调用方，在新契约下会不会坏？

三件事决定了它比"比字符串"难：
    ① $ref 必须展开后再比      —— 只比 "$ref 字符串" 会漏判
    ② oneOf/anyOf 顺序无意义   —— 不归一化会误报
    ③ 请求侧和响应侧方向相反   —— 入参"收紧"是破坏，出参"放宽"才是破坏
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .rules import BREAKING, RISKY, SAFE, ORDER, worst

_ONE_OF_KEYS = ("oneOf", "anyOf", "allOf")
_TIGHTEN_UP = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
_TIGHTEN_DOWN = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")

# 我们"真正比较过"或"确认无需比较"的关键字。
# 不在这张表里的关键字一旦出现/变化 → 一律 RISKY 转人工 review（宁报不漏）。
# 这条设计抄自 ToolDelta："Unsupported keywords require review even when unchanged"。
_KNOWN_KEYS = frozenset({
    # 结构
    "type", "properties", "required", "items", "prefixItems", "additionalProperties",
    "oneOf", "anyOf", "allOf", "not", "if", "then", "else",
    "dependentRequired", "dependentSchemas", "dependencies", "propertyNames",
    # 取值约束
    "enum", "const", "pattern", "format", "multipleOf",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
    "contains", "minContains", "maxContains", "minProperties", "maxProperties",
    # 元数据（不影响调用，已知即可）
    "title", "description", "default", "examples", "deprecated",
    "readOnly", "writeOnly", "$schema", "$id", "$comment", "$defs", "definitions",
    "contentMediaType", "contentEncoding", "contentSchema", "discriminator", "nullable",
})


@dataclass(frozen=True)
class Finding:
    tool: str
    path: str
    kind: str
    severity: str
    detail: str


def _canon(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- 预处理


def _resolve(node, root, depth: int = 0):
    """展开本地 $ref（#/...）。展开后再比，才不会只比了个指针字符串。"""
    if depth > 20:
        return node
    if isinstance(node, list):
        return [_resolve(x, root, depth + 1) for x in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        target = root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target.get(part, {}) if isinstance(target, dict) else {}
        resolved = _resolve(target, root, depth + 1)
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        if siblings and isinstance(resolved, dict):
            resolved = {**resolved, **siblings}
            return _resolve(resolved, root, depth + 1)
        return resolved
    return {k: _resolve(v, root, depth + 1) for k, v in node.items()}


def _normalize(node):
    """oneOf/anyOf/allOf 的顺序没有语义，排序后再比，避免纯误报。"""
    if isinstance(node, list):
        return [_normalize(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in _ONE_OF_KEYS and isinstance(value, list):
            out[key] = sorted((_normalize(x) for x in value), key=_canon)
        else:
            out[key] = _normalize(value)
    return out


def prepare_schema(doc: dict | None) -> dict:
    """快照里的一份 schema → 可比较的形态（先展开 $ref，再归一化顺序）。"""
    if not doc:
        return {}
    return _normalize(_resolve(doc, doc))


# ---------------------------------------------------------------- 比较


def _add(out: list[Finding], tool: str, path: str, kind: str, sev: str, detail: str) -> None:
    out.append(Finding(tool=tool, path=path, kind=kind, severity=sev, detail=detail))


def _diff_enum(old: dict, new: dict, out: list, tool: str, path: str, side: str) -> None:
    old_enum, new_enum = old.get("enum"), new.get("enum")
    if not (isinstance(old_enum, list) and isinstance(new_enum, list)):
        return
    o = {_canon(x) for x in old_enum}
    n = {_canon(x) for x in new_enum}
    if side == "request":
        removed, added = o - n, n - o
        if removed:
            _add(out, tool, f"{path}.enum", "enum_shrunk", BREAKING,
                 f"入参 enum 缩小，老取值不再合法: {sorted(removed)}")
        if added:
            _add(out, tool, f"{path}.enum", "enum_expanded", SAFE,
                 f"入参 enum 扩大: {sorted(added)}")
    else:
        added = n - o
        if added:
            _add(out, tool, f"{path}.enum", "response_enum_expanded", BREAKING,
                 f"返回 enum 扩大，老客户端不认识新值: {sorted(added)}")


def _diff_range(old: dict, new: dict, out: list, tool: str, path: str, side: str) -> None:
    if side != "request":
        return
    for key in _TIGHTEN_UP:
        if key not in new:
            continue
        if key not in old:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING,
                 f"新增下限 {key}={new[key]}，老取值可能越界")
        elif new[key] > old[key]:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING,
                 f"{key} 从 {old[key]} 提高到 {new[key]}")
    for key in _TIGHTEN_DOWN:
        if key not in new:
            continue
        if key not in old:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING,
                 f"新增上限 {key}={new[key]}，老取值可能越界")
        elif new[key] < old[key]:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING,
                 f"{key} 从 {old[key]} 降到 {new[key]}")


def _diff_object(old: dict, new: dict, out: list, tool: str, path: str, side: str) -> None:
    old_props = old.get("properties") or {}
    new_props = new.get("properties") or {}
    old_req = set(old.get("required") or [])
    new_req = set(new.get("required") or [])

    if isinstance(old_props, dict) and isinstance(new_props, dict):
        for name in sorted(set(old_props) - set(new_props)):
            if side == "request":
                _add(out, tool, f"{path}.{name}", "prop_removed", BREAKING,
                     f"入参 {name} 被删除")
            else:
                _add(out, tool, f"{path}.{name}", "response_prop_removed", BREAKING,
                     f"返回字段 {name} 被删除")

        for name in sorted(set(new_props) - set(old_props)):
            if side == "request":
                sev = BREAKING if name in new_req else SAFE
                kind = "prop_added_required" if sev is BREAKING else "prop_added_optional"
                _add(out, tool, f"{path}.{name}", kind, sev,
                     f"新增入参 {name}（{'必填' if sev is BREAKING else '可选'}）")

        for name in sorted(set(old_props) & set(new_props)):
            _diff_node(old_props[name], new_props[name], out, tool, f"{path}.{name}", side)

    # required 集合变化（新增的 property 已经在上面报过，不重复）
    for name in sorted(new_req - old_req):
        if name in old_props:
            if side == "request":
                _add(out, tool, f"{path}.{name}", "required_added", BREAKING,
                     f"{name} 由可选变必填（即使有 default 也一样）")
            else:
                _add(out, tool, f"{path}.{name}", "response_required_added", SAFE,
                     f"返回字段 {name} 变为必有")
    for name in sorted(old_req - new_req):
        if side == "request":
            _add(out, tool, f"{path}.{name}", "required_removed", SAFE,
                 f"{name} 由必填变可选")
        else:
            _add(out, tool, f"{path}.{name}", "response_required_removed", BREAKING,
                 f"返回字段 {name} 不再保证存在")

    if old.get("additionalProperties", True) is not False and new.get("additionalProperties") is False:
        if side == "request":
            _add(out, tool, f"{path}.additionalProperties", "additional_props_closed", BREAKING,
                 "additionalProperties 改为 false，老调用多传的字段会被拒")


def _diff_unsupported(old: dict, new: dict, out: list, tool: str, path: str) -> None:
    """没见过的关键字 → 转人工 review。

    为什么这条重要：静默放过 = 给调用方一个**虚假的通过信号**。
    漏报比误报贵得多 —— 误报可以关掉，漏报会在线上炸。
    """
    for key in sorted(set(old) | set(new)):
        if key in _KNOWN_KEYS or key.startswith("x-"):
            continue
        if old.get(key) != new.get(key):
            _add(out, tool, f"{path}.{key}", "unsupported_keyword", RISKY,
                 f"未支持的 JSON Schema 关键字 `{key}` 发生变化 → 转人工 review")


def _diff_node(old, new, out: list, tool: str, path: str, side: str) -> None:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return

    if old.get("type") and new.get("type") and old["type"] != new["type"]:
        _add(out, tool, path, "type_changed", BREAKING,
             f"类型 {old['type']} → {new['type']}")

    if old.get("const") != new.get("const") and new.get("const") is not None:
        _add(out, tool, f"{path}.const", "const_changed", BREAKING,
             f"const {old.get('const')!r} → {new.get('const')!r}（取值被钉死）")

    if old.get("pattern") != new.get("pattern"):
        _add(out, tool, f"{path}.pattern", "pattern_changed", RISKY,
             "正则变化：无法程序化判定包含关系 → 转人工 review")

    if "description" in old and "description" in new and old["description"] != new["description"]:
        _add(out, tool, f"{path}.description", "description_changed", RISKY,
             "描述变化：不影响代码，但会影响模型选工具")

    if "default" in old or "default" in new:
        if old.get("default") != new.get("default"):
            _add(out, tool, f"{path}.default", "default_changed", RISKY,
                 f"default {old.get('default')!r} → {new.get('default')!r}")

    _diff_enum(old, new, out, tool, path, side)
    _diff_range(old, new, out, tool, path, side)

    for key in _ONE_OF_KEYS:
        if key in old and key in new:
            if _canon(old[key]) != _canon(new[key]):
                _add(out, tool, f"{path}.{key}", "union_changed", RISKY,
                     f"{key} 分支内容变化（顺序不同不算）")

    if isinstance(old.get("items"), dict) and isinstance(new.get("items"), dict):
        _diff_node(old["items"], new["items"], out, tool, f"{path}[]", side)

    _diff_object(old, new, out, tool, path, side)
    _diff_unsupported(old, new, out, tool, path)


# ---------------------------------------------------------------- 入口


def diff_tool(name: str, old: dict, new: dict) -> list[Finding]:
    """比一个工具的契约。old/new 形如 {description, input_schema, output_schema}。"""
    out: list[Finding] = []

    if old.get("description") != new.get("description"):
        _add(out, name, f"{name}.description", "description_changed", RISKY,
             "工具描述变化：模型选工具的输入变了")

    _diff_node(
        prepare_schema(old.get("input_schema")), prepare_schema(new.get("input_schema")),
        out, name, f"{name}.input", "request",
    )

    old_out, new_out = old.get("output_schema"), new.get("output_schema")
    if old_out and not new_out:
        _add(out, name, f"{name}.output", "output_schema_removed", RISKY,
             "返回 schema 不再声明，客户端无法校验返回值")
    elif old_out and new_out:
        _diff_node(prepare_schema(old_out), prepare_schema(new_out),
                   out, name, f"{name}.output", "response")

    return out


def diff_snapshots(old_tools: dict, new_tools: dict) -> list[Finding]:
    """比两份快照（tools.json 的内容）。"""
    out: list[Finding] = []
    for name in sorted(set(old_tools) - set(new_tools)):
        _add(out, name, name, "tool_removed", BREAKING, "工具被删除")
    for name in sorted(set(new_tools) - set(old_tools)):
        _add(out, name, name, "tool_added", SAFE, "新增工具（放进评测看选择干扰）")
    for name in sorted(set(old_tools) & set(new_tools)):
        out.extend(diff_tool(name, old_tools[name], new_tools[name]))
    return out


__all__ = [
    "Finding",
    "prepare_schema",
    "diff_tool",
    "diff_snapshots",
    "worst",
    "ORDER",
]
