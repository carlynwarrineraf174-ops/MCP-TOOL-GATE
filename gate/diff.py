"""schema 语义 diff —— 这个项目的"心脏"。

它只回答一个问题：
    一个按旧契约写的调用方，在新契约下会不会坏？
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .rules import BREAKING, RISKY, SAFE, ORDER, worst

_ONE_OF_KEYS = ("oneOf", "anyOf", "allOf")
_TIGHTEN_UP = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
_TIGHTEN_DOWN = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")

_KNOWN_KEYS = frozenset({
    "type", "properties", "required", "items", "prefixItems", "additionalProperties",
    "oneOf", "anyOf", "allOf", "not", "if", "then", "else",
    "dependentRequired", "dependentSchemas", "dependencies", "propertyNames",
    "enum", "const", "pattern", "format", "multipleOf",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
    "contains", "minContains", "maxContains", "minProperties", "maxProperties",
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


def _type_set(node: dict) -> set | None:
    t = node.get("type")
    if t is None:
        return None
    return set(t) if isinstance(t, list) else {t}


# ---------------------------------------------------------------- 预处理

def _resolve(node, root, depth: int = 0):
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


_EQ_DROP = frozenset({"title", "$comment", "$id", "$schema", "examples"})

def _simplify(node):
    if isinstance(node, list):
        return [_simplify(x) for x in node]
    if not isinstance(node, dict):
        return node
    for key in _ONE_OF_KEYS:
        branches = node.get(key)
        if isinstance(branches, list) and len(branches) == 1 and len(node) == 1:
            return _simplify(branches[0])
    out = {}
    for key, value in node.items():
        if key in _EQ_DROP:
            continue
        if key == "type" and isinstance(value, list) and len(value) == 1:
            out[key] = value[0]
            continue
        if key == "required" and value == []:
            continue
        if key == "additionalProperties" and value is True:
            continue
        out[key] = _simplify(value)
    return out


def prepare_schema(doc: dict | None) -> dict:
    if not doc:
        return {}
    return _normalize(_simplify(_resolve(doc, doc)))


# ---------------------------------------------------------------- 比较

def _add(out: list[Finding], tool: str, path: str, kind: str, sev: str, detail: str) -> None:
    out.append(Finding(tool=tool, path=path, kind=kind, severity=sev, detail=detail))


def _diff_enum(old: dict, new: dict, out: list, tool: str, path: str, side: str) -> None:
    old_enum, new_enum = old.get("enum"), new.get("enum")
    if old_enum is None and new_enum is None:
        return
    o = {_canon(x) for x in old_enum} if isinstance(old_enum, list) else None
    n = {_canon(x) for x in new_enum} if isinstance(new_enum, list) else None

    if o is None and n is not None:
        if side == "request":
            _add(out, tool, f"{path}.enum", "enum_added", BREAKING,
                 f"新增 enum（原来接受任意值），老取值可能非法: {sorted(n)}")
        return
    if o is None or n is None:
        return
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
        if key not in new: continue
        if key not in old:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING, f"新增下限 {key}={new[key]}")
        else:
            ov, nv = old[key], new[key]
            if not isinstance(ov, (int, float)) or not isinstance(nv, (int, float)) or isinstance(ov, bool) or isinstance(nv, bool):
                _add(out, tool, f"{path}.{key}", "unsupported_value", RISKY, f"{key} 类型非数值（{ov!r} -> {nv!r}），转人工确认")
                continue
            if nv > ov:
                _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING, f"{key} 从 {ov} 提高到 {nv}")
    for key in _TIGHTEN_DOWN:
        if key not in new: continue
        if key not in old:
            _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING, f"新增上限 {key}={new[key]}")
        else:
            ov, nv = old[key], new[key]
            if not isinstance(ov, (int, float)) or not isinstance(nv, (int, float)) or isinstance(ov, bool) or isinstance(nv, bool):
                _add(out, tool, f"{path}.{key}", "unsupported_value", RISKY, f"{key} 类型非数值（{ov!r} -> {nv!r}），转人工确认")
                continue
            if nv < ov:
                _add(out, tool, f"{path}.{key}", "range_tightened", BREAKING, f"{key} 从 {ov} 降到 {nv}")


def _diff_object(old: dict, new: dict, out: list, tool: str, path: str, side: str) -> None:
    old_props, new_props = old.get("properties") or {}, new.get("properties") or {}
    old_req, new_req = set(old.get("required") or []), set(new.get("required") or [])

    if isinstance(old_props, dict) and isinstance(new_props, dict):
        for name in sorted(set(old_props) - set(new_props)):
            _add(out, tool, f"{path}.{name}", "prop_removed" if side == "request" else "response_prop_removed", BREAKING, f"入参 {name} 被删除" if side == "request" else f"返回字段 {name} 被删除")
        for name in sorted(set(new_props) - set(old_props)):
            if side == "request":
                sev = BREAKING if name in new_req else SAFE
                _add(out, tool, f"{path}.{name}", "prop_added_required" if sev is BREAKING else "prop_added_optional", sev, f"新增入参 {name}")
        for name in sorted(set(old_props) & set(new_props)):
            _diff_node(old_props[name], new_props[name], out, tool, f"{path}.{name}", side)

    for name in sorted(new_req - old_req):
        if name in old_props:
            _add(out, tool, f"{path}.{name}", "required_added" if side == "request" else "response_required_added", BREAKING if side == "request" else SAFE, f"{name} 由可选变必填" if side == "request" else f"返回字段 {name} 变为必有")
    for name in sorted(old_req - new_req):
        _add(out, tool, f"{path}.{name}", "required_removed" if side == "request" else "response_required_removed", SAFE if side == "request" else BREAKING, f"{name} 由必填变可选" if side == "request" else f"返回字段 {name} 不再保证存在")

    old_dep, new_dep = old.get("dependentRequired") or {}, new.get("dependentRequired") or {}
    for key in sorted(new_dep):
        if set(new_dep[key]) - set(old_dep.get(key) or []):
            _add(out, tool, f"{path}.dependentRequired.{key}", "dependent_required_added", BREAKING, f"存在{key}时新增必填")

    old_ap, new_ap = old.get("additionalProperties"), new.get("additionalProperties")
    # 先把 True / None 归一到"无约束"
    old_ap_unbounded = old_ap is None or old_ap is True

    if isinstance(old_ap, dict) and isinstance(new_ap, dict):
        # schema → schema：递归比
        _diff_node(old_ap, new_ap, out, tool, f"{path}.additionalProperties", side)

    elif old_ap_unbounded and isinstance(new_ap, dict):
        # 无约束 → schema：收紧（原来任意字段都合法，现在受类型约束）
        if side == "request":
            _add(out, tool, f"{path}.additionalProperties", "additional_props_tightened", BREAKING,
                 "additionalProperties 由无约束改为 schema（老调用多传的字段可能非法）")

    elif isinstance(old_ap, dict) and new_ap is False:
        # schema → false：改为拒绝（保留原逻辑）
        if side == "request":
            _add(out, tool, f"{path}.additionalProperties", "additional_props_closed", BREAKING,
                 "additionalProperties 从 schema 改为 false")

    elif new_ap is False:
        # 剩下所有 → false（含 None/True → false）：一律拒绝
        if side == "request":
            _add(out, tool, f"{path}.additionalProperties", "additional_props_closed", BREAKING,
                 "additionalProperties 改为 false")

def _diff_unsupported(old: dict, new: dict, out: list, tool: str, path: str) -> None:
    for key in sorted(set(old) | set(new)):
        if key in _KNOWN_KEYS or key.startswith("x-"): continue
        if old.get(key) != new.get(key):
            _add(out, tool, f"{path}.{key}", "unsupported_keyword", RISKY, f"未支持的关键字 {key} 变化")


def _diff_node(old, new, out: list, tool: str, path: str, side: str) -> None:
    # 先处理布尔 schema：false 等价于"拒绝一切"，true 等价于"接受一切"
    old_is_false = old is False
    new_is_false = new is False

    if old_is_false and not new_is_false:
        # false → 任意 = 放宽，静默
        return
    if not old_is_false and new_is_false:
        # 任意 → false = 请求侧收紧，BREAKING
        if side == "request":
            _add(out, tool, path, "schema_rejected", BREAKING,
                 "schema 由可接受改为 false（拒绝一切值）")
        return

    # 剩下的 True（等价 {}）、dict 都归一化后继续比
    if old is True: old = {}
    if new is True: new = {}
    if old is False or new is False:
        # 两边都是 False（无变化）
        return

    if not isinstance(old, dict) or not isinstance(new, dict): return

    old_t, new_t = _type_set(old), _type_set(new)
    if old_t is None and new_t is not None:
        if side == "request":
            _add(out, tool, path, "type_restricted", BREAKING, f"新增类型约束 {sorted(new_t)}")
    elif old_t is not None and new_t is not None:
        dropped = old_t - new_t
        if dropped:
            _add(out, tool, path, "type_changed", BREAKING, f"类型 {sorted(old_t)} → {sorted(new_t)}")

    if old.get("const") != new.get("const") and new.get("const") is not None:
        _add(out, tool, f"{path}.const", "const_changed", BREAKING, "取值被钉死")
    if old.get("pattern") != new.get("pattern"):
        _add(out, tool, f"{path}.pattern", "pattern_changed", RISKY, "正则变化 → 转人工")
    if "description" in old and "description" in new and old["description"] != new["description"]:
        _add(out, tool, f"{path}.description", "description_changed", RISKY, "描述变化")
    if "default" in old or "default" in new:
        if old.get("default") != new.get("default"):
            _add(out, tool, f"{path}.default", "default_changed", RISKY, "default 变化")
    if old.get("format") != new.get("format"):
        _add(out, tool, f"{path}.format", "format_changed", RISKY, "format 变化")

    _diff_enum(old, new, out, tool, path, side)
    _diff_range(old, new, out, tool, path, side)

    for key in _ONE_OF_KEYS:
        if key in old and key in new and _canon(old[key]) != _canon(new[key]):
            _add(out, tool, f"{path}.{key}", "union_changed", RISKY, "分支内容变化")

    old_items, new_items = old.get("items"), new.get("items")
    if isinstance(old_items, dict) and isinstance(new_items, dict):
        _diff_node(old_items, new_items, out, tool, f"{path}[]", side)
    elif isinstance(old_items, list) and isinstance(new_items, list):
        for i, (oi, ni) in enumerate(zip(old_items, new_items)):
            _diff_node(oi, ni, out, tool, f"{path}[{i}]", side)
        if side == "request":
            if len(new_items) < len(old_items):
                _add(out, tool, f"{path}.items", "items_restricted", BREAKING,
                     f"tuple items 从 {len(old_items)} 项缩到 {len(new_items)} 项")
            elif len(new_items) > len(old_items):
                _add(out, tool, f"{path}.items", "items_restricted", BREAKING,
                     f"tuple items 从 {len(old_items)} 项扩到 {len(new_items)} 项（新增位置约束，老数组可能越界）")
    elif side == "request" and not isinstance(old_items, (dict, list)) and isinstance(new_items, (dict, list)):
        _add(out, tool, f"{path}.items", "items_restricted", BREAKING, "新增数组元素约束")

    if old.get("readOnly") is not True and new.get("readOnly") is True:
        _add(out, tool, f"{path}.readOnly", "readonly_added", BREAKING, "变为 readOnly")
    if old.get("uniqueItems") is not True and new.get("uniqueItems") is True:
        _add(out, tool, f"{path}.uniqueItems", "unique_items_changed", BREAKING, "现在会被拒重复值")
    if old.get("prefixItems") != new.get("prefixItems"):
        _add(out, tool, f"{path}.prefixItems", "prefix_items_changed", RISKY, "数组结构变化")

    _diff_object(old, new, out, tool, path, side)
    _diff_unsupported(old, new, out, tool, path)


def diff_tool(name: str, old: dict, new: dict) -> list[Finding]:
    out: list[Finding] = []
    if old.get("description") != new.get("description"):
        _add(out, name, f"{name}.description", "description_changed", RISKY, "工具描述变化")
    _diff_node(prepare_schema(old.get("input_schema")), prepare_schema(new.get("input_schema")), out, name, f"{name}.input", "request")
    old_out, new_out = old.get("output_schema"), new.get("output_schema")
    if old_out and not new_out:
        _add(out, name, f"{name}.output", "output_schema_removed", RISKY, "不再声明返回 schema")
    elif old_out and new_out:
        _diff_node(prepare_schema(old_out), prepare_schema(new_out), out, name, f"{name}.output", "response")
    return out


def diff_snapshots(old_tools: dict, new_tools: dict) -> list[Finding]:
    out: list[Finding] = []
    for name in sorted(set(old_tools) - set(new_tools)):
        _add(out, name, name, "tool_removed", BREAKING, "工具被删除")
    for name in sorted(set(new_tools) - set(old_tools)):
        _add(out, name, name, "tool_added", SAFE, "新增工具")
    for name in sorted(set(old_tools) & set(new_tools)):
        try:
            out.extend(diff_tool(name, old_tools[name], new_tools[name]))
        except Exception as e:
            _add(out, name, name, "engine_crash", RISKY, f"diff 引擎异常：{type(e).__name__}: {e}")
    return out