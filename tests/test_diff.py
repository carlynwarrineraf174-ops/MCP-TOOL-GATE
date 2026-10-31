"""diff 引擎的回归测试。

每个用例对应 rules.py 里的一条规则；**负例（不该报）和正例一样重要**：
门禁误报一次，团队就会把它关掉——这是 lab_04 跑出来的真实结论。
"""

from __future__ import annotations

import unittest

from gate.diff import diff_snapshots, prepare_schema
from gate.rules import BREAKING, RISKY, SAFE, worst


def tool(input_schema: dict, description: str = "查询天气", output_schema: dict | None = None) -> dict:
    return {"description": description, "input_schema": input_schema, "output_schema": output_schema}


def obj(**props) -> dict:
    return {"type": "object", "properties": props}


STR = {"type": "string"}


class DiffTest(unittest.TestCase):
    def kinds(self, old: dict, new: dict) -> set[str]:
        return {f.kind for f in diff_snapshots({"t": old}, {"t": new})}

    # ---- 请求侧：收紧 = 破坏 ----
    def test_required_added_is_breaking(self):
        old = tool(obj(city=STR))
        new = tool({**obj(city=STR), "required": ["city"]})
        f = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("required_added", {x.kind for x in f})
        self.assertEqual(worst(f), BREAKING)

    def test_required_added_with_default_is_still_breaking(self):
        """这是 oasdiff 的那句话：default 是服务端兜底，不是契约。"""
        old = tool(obj(city=STR))
        new = tool({"type": "object", "properties": {"city": {**STR, "default": "北京"}}, "required": ["city"]})
        f = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("required_added", {x.kind for x in f})
        self.assertEqual(worst(f), BREAKING)

    def test_prop_removed_is_breaking(self):
        f = diff_snapshots({"t": tool(obj(city=STR, unit=STR))}, {"t": tool(obj(city=STR))})
        self.assertIn("prop_removed", {x.kind for x in f})

    def test_prop_added_required_is_breaking_optional_is_safe(self):
        old = tool(obj(city=STR))
        new = tool(obj(city=STR, lang=STR))
        self.assertEqual(self.kinds(old, new), {"prop_added_optional"})
        self.assertEqual(worst(diff_snapshots({"t": old}, {"t": new})), SAFE)

        new_req = tool({"type": "object", "properties": {"city": STR, "lang": STR}, "required": ["lang"]})
        f = diff_snapshots({"t": old}, {"t": new_req})
        self.assertIn("prop_added_required", {x.kind for x in f})
        self.assertEqual(worst(f), BREAKING)

    def test_enum_shrunk_breaking_expanded_safe(self):
        old = tool(obj(city={"type": "string", "enum": ["a", "b"]}))
        shrunk = tool(obj(city={"type": "string", "enum": ["a"]}))
        expanded = tool(obj(city={"type": "string", "enum": ["a", "b", "c"]}))
        self.assertEqual(worst(diff_snapshots({"t": old}, {"t": shrunk})), BREAKING)
        self.assertEqual(worst(diff_snapshots({"t": old}, {"t": expanded})), SAFE)

    def test_type_changed_is_breaking(self):
        f = diff_snapshots({"t": tool(obj(top_k={"type": "integer"}))},
                           {"t": tool(obj(top_k={"type": "string"}))})
        self.assertIn("type_changed", {x.kind for x in f})

    def test_range_tightened_is_breaking(self):
        old = tool(obj(top_k={"type": "integer", "maximum": 100}))
        new = tool(obj(top_k={"type": "integer", "maximum": 10}))
        self.assertIn("range_tightened", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    def test_new_upper_bound_is_tightening(self):
        """原来没有上限 = 任意值都能传，新增 maximum 就是收紧。"""
        old = tool(obj(top_k={"type": "integer"}))
        new = tool(obj(top_k={"type": "integer", "maximum": 5}))
        self.assertIn("range_tightened", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    def test_loosening_range_is_silent(self):
        """放宽范围是兼容的，不该报警（负例）。"""
        old = tool(obj(top_k={"type": "integer", "maximum": 5}))
        new = tool(obj(top_k={"type": "integer", "maximum": 50}))
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_additional_props_closed_is_breaking(self):
        old = tool({"type": "object", "properties": {"city": STR}})
        new = tool({"type": "object", "properties": {"city": STR}, "additionalProperties": False})
        self.assertIn("additional_props_closed", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    # ---- RISKY：不影响代码，影响行为/模型 ----
    def test_description_changed_is_risky(self):
        f = diff_snapshots({"t": tool(obj(city=STR), description="查天气")},
                           {"t": tool(obj(city=STR), description="查实时天气")})
        self.assertIn("description_changed", {x.kind for x in f})
        self.assertEqual(worst(f), RISKY)

    def test_default_changed_is_risky(self):
        old = tool(obj(unit={**STR, "default": "c"}))
        new = tool(obj(unit={**STR, "default": "f"}))
        self.assertIn("default_changed", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    # ---- 响应侧：方向相反 ----
    def test_response_prop_removed_is_breaking(self):
        old = tool(obj(city=STR), output_schema={"type": "object", "properties": {"temp": {"type": "number"}}})
        new = tool(obj(city=STR), output_schema={"type": "object", "properties": {}})
        self.assertIn("response_prop_removed", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    def test_response_enum_expanded_is_breaking(self):
        old = tool(obj(city=STR), output_schema={"type": "object", "properties": {"s": {"type": "string", "enum": ["OK"]}}})
        new = tool(obj(city=STR), output_schema={"type": "object", "properties": {"s": {"type": "string", "enum": ["OK", "FAIL"]}}})
        self.assertIn("response_enum_expanded", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    # ---- 负例：这些不该报警 ----
    def test_oneof_reorder_is_not_a_change(self):
        a = {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}}
        b = {"type": "object", "properties": {"x": {"oneOf": [{"type": "integer"}, {"type": "string"}]}}}
        self.assertEqual(diff_snapshots({"t": tool(a)}, {"t": tool(b)}), [])

    def test_identical_snapshot_is_clean(self):
        t = tool(obj(city=STR))
        self.assertEqual(diff_snapshots({"t": t}, {"t": t}), [])

    # ---- 保守策略：看不懂的一律转人工 review ----
    def test_const_changed_is_breaking(self):
        old = tool(obj(unit={"type": "string"}))
        new = tool(obj(unit={"type": "string", "const": "c"}))
        self.assertIn("const_changed", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    def test_pattern_changed_is_risky(self):
        old = tool(obj(order_id={"type": "string", "pattern": "^[A-Z]"}))
        new = tool(obj(order_id={"type": "string", "pattern": "^[A-Z]{2}"}))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("pattern_changed", {x.kind for x in found})
        self.assertEqual(worst(found), RISKY)

    def test_unknown_keyword_is_risky(self):
        """没见过的关键字变化 → 必须转人工，不能静默通过。"""
        old = tool(obj(city={**STR, "readOnlyForAgents": True}))
        new = tool(obj(city={**STR, "readOnlyForAgents": False}))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("unsupported_keyword", {x.kind for x in found})
        self.assertEqual(worst(found), RISKY)

    def test_unknown_keyword_unchanged_is_silent(self):
        """负例：不认识但没变的关键字，不该刷屏。"""
        schema = {"type": "object", "properties": {"city": {**STR, "readOnlyForAgents": True}}}
        self.assertEqual(diff_snapshots({"t": tool(schema)}, {"t": tool(schema)}), [])

    def test_title_change_is_silent(self):
        """负例：title 只是 UI 元数据，改它不该报警。"""
        old = tool(obj(city={"type": "string", "title": "City"}))
        new = tool(obj(city={"type": "string", "title": "城市"}))
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    # ---- $ref：只比指针字符串会漏判 ----
    def test_ref_expanded_then_compared(self):
        old_inner = {"type": "string"}
        new_inner = {"type": "integer"}
        old = tool({"type": "object", "properties": {"city": {"$ref": "#/$defs/City"}}, "$defs": {"City": old_inner}})
        new = tool({"type": "object", "properties": {"city": {"$ref": "#/$defs/City"}}, "$defs": {"City": new_inner}})
        self.assertEqual(prepare_schema(old["input_schema"])["properties"]["city"], old_inner)
        self.assertIn("type_changed", {x.kind for x in diff_snapshots({"t": old}, {"t": new})})

    def test_dependent_required_added_is_breaking(self):
        old = tool({"type":"object","properties":{"card": STR, "addr": STR}})
        new = tool({"type":"object","properties":{"card": STR, "addr": STR}, "dependentRequired":{"card": ["addr"]}})

        found = diff_snapshots({"t": old},{"t": new})
        self.assertIn("dependent_required_added", {x.kind for x in found})
        self.assertEqual(worst(found),BREAKING)

    def test_dependent_required_removed_is_safe(self):
        old = tool({"type": "object", "properties": {"card": STR, "addr": STR}, "dependentRequired":{"card": ["addr"]}})
        new = tool({"type": "object", "properties": {"card": STR, "addr": STR}})
        self.assertEqual(diff_snapshots({"t": old},{"t": new}), [])


    def test_format_changed(self):
        old = tool(obj(birthday = {"type": "string", "format": "date"}))
        new = tool(obj(birthday = {"type": "string", "format": "date-time"}))
        found = diff_snapshots({"t" : old}, {"t": new})
        self.assertIn("format_changed",{x.kind for x in found})
        self.assertEqual(worst(found), RISKY)


    def test_readonly_added_is_breaking(self):
        old = tool(obj(city = STR))
        new = tool(obj(city = {**STR, "readOnly" : True}))
        found = diff_snapshots({"t" : old},{"t": new})
        self.assertIn("readonly_added",{x.kind for x in found})
        self.assertEqual(worst(found),BREAKING)

        old1 = tool(obj(city = {**STR, "readOnly" : True}))
        new1 = tool(obj(city = {**STR, "readOnly" : False}))
        found1 = diff_snapshots({"t": old1},{"t": new1})
        self.assertEqual(found1,[])

    def test_unique_items_changed_is_breaking(self):
        old = tool(obj(city = {**STR, "uniqueItems" : False}))
        new = tool(obj(city = {**STR, "uniqueItems" : True}))
        found = diff_snapshots({"t" : old},{"t" : new})
        self.assertIn("unique_items_changed",{x.kind for x in found})
        self.assertEqual(worst(found),BREAKING)

        old1 = tool(obj(city = {**STR, "uniqueItems" : True}))
        new1 = tool(obj(city = {**STR, "uniqueItems" : False}))
        found1 = diff_snapshots({"t" : old1},{"t": new1})
        self.assertEqual(found1 , [])

    def test_prefix_items_changed_is_risky(self):
        old = tool(obj(tag={"type": "array", "prefixItems": [{"type": "string"}]}))
        new = tool(obj(tag = {"type": "array", "prefixItems": [{"type": "integer"}]}))
        found = diff_snapshots({"t": old},{"t": new})
        self.assertIn("prefix_items_changed",{x.kind for x in found})
        self.assertEqual(worst(found),RISKY)

        old1 = tool(obj(tag={"type": "array", "prefixItems": [{"type": "string"}]}))
        new1 = tool(obj(tag = {"type": "array", "prefixItems": [{"type": "string"}]}))
        found1 = diff_snapshots({"t": old1},{"t": new1})
        self.assertEqual(found1, [])

    #     # ---- 边界：从「无」到「有」的收紧（漏判高发区） ----

    def test_enum_added_where_none_is_breaking(self):
        old = tool(obj(reason = STR))
        new = tool(obj(reason = {"type": "string", "enum": ["error"]}))
        found = diff_snapshots({"t": old},{"t": new})
        self.assertIn("enum_added", {x.kind for x in found})
        self.assertEqual(worst(found), BREAKING)



    def test_type_added_where_none_is_breaking(self):
        old = tool(obj(city = {"description" : "城市"}))
        new = tool(obj(city = {"description" : "城市", "type" : "string"}))
        found = diff_snapshots({"t": old},{"t": new})
        self.assertIn("type_restricted",{x.kind for x in found})
        self.assertEqual(worst(found), BREAKING)

    def test_items_added_is_breaking(self):
        old = tool(obj(tag = {"type": "array"}))
        new = tool(obj(tag = {"type" : "array", "items" : {"type": "string"}}))
        found = diff_snapshots({"t": old},{"t":new})
        self.assertIn("items_restricted",{x.kind for x in found})
        self.assertEqual(worst(found),BREAKING)
    #     # ---- 边界：nullable 是「放宽」，不该报警（负例，之前是误报） ----

    def test_type_nullable_added_is_silent(self):
        old = tool(obj(city = {"type" : "string"}))
        new = tool(obj(city = {"type": ["string", "null"]}))
        found = diff_snapshots({"t": old},{"t": new})
        self.assertEqual(found, [])



    def test_type_nullable_removed_is_breaking(self):
        old = tool(obj(city = {"type" : ["string","null" ]}))
        new = tool(obj(city = {"type" : "string"}))
        found = diff_snapshots({"t": old},{"t":new})
        self.assertEqual(worst(found),BREAKING)



    def test_enum_removed_is_silent(self):
        old = tool(obj(reason = {"type": "string", "enum": ["a"]}))
        new = tool(obj(reason = {"type": "string"}))
        found = diff_snapshots({"t":old},{"t":new})
        self.assertEqual(found,[])

    # ---- 语义等价：写法不同、意思相同，不该报警（outputSchema 尤其常见） ----
    def test_output_allof_single_branch_is_equivalent(self):
        """输出 schema 外面多包一层 allOf，语义没变 → 不该报"返回字段被删除"。"""
        inner = {"type": "object", "properties": {"t": {"type": "number"}}}
        old = tool(obj(city=STR), output_schema=inner)
        new = tool(obj(city=STR), output_schema={"allOf": [inner]})
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_output_single_element_type_list_is_equivalent(self):
        old = tool(obj(city=STR),
                   output_schema={"type": "object", "properties": {"t": {"type": "number"}}})
        new = tool(obj(city=STR),
                   output_schema={"type": ["object"], "properties": {"t": {"type": ["number"]}}})
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_output_empty_required_and_open_additional_props_are_equivalent(self):
        old = tool(obj(city=STR),
                   output_schema={"type": "object", "properties": {"t": {"type": "number"}}})
        new = tool(obj(city=STR),
                   output_schema={"type": "object", "properties": {"t": {"type": "number"}},
                                  "required": [], "additionalProperties": True})
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_output_pure_metadata_change_is_silent(self):
        old = tool(obj(city=STR), output_schema={
            "type": "object", "title": "A", "examples": [1],
            "properties": {"t": {"type": "number"}}})
        new = tool(obj(city=STR), output_schema={
            "type": "object", "title": "B", "examples": [2],
            "properties": {"t": {"type": "number"}}})
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_single_branch_oneof_is_equivalent(self):
        old = tool(obj(f={"oneOf": [{"type": "string"}]}))
        new = tool(obj(f={"type": "string"}))
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    def test_equivalence_must_not_swallow_real_change(self):
        """负例的负例：归一化不能把真变更也吃掉。"""
        old = tool(obj(city=STR), output_schema={"type": "object",
                                                "properties": {"t": {"type": "number"}}})
        new = tool(obj(city=STR), output_schema={"allOf": [
            {"type": "object", "properties": {"t": {"type": "string"}}}]})
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("type_changed", {f.kind for f in found})

    # ---- P0-1: additionalProperties 的「从无到有」 ----
    def test_additional_props_none_to_schema_is_breaking(self):
        """老：不加约束（任意字段合法）；新：字段受 schema 约束 → 收紧。"""
        old = tool(obj(a=STR))
        new = tool({**obj(a=STR), "additionalProperties": {"type": "string"}})
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("additional_props_tightened", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)




    def test_additional_props_schema_to_schema_recurses(self):
        """dict → dict 已修，这里锁住不回归。"""
        old = tool({**obj(a=STR), "additionalProperties": {"type": "string"}})
        new = tool({**obj(a=STR), "additionalProperties": {"type": "integer"}})
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("type_changed", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)




    def test_additional_props_schema_to_false_is_breaking(self):
        """dict → false 已修，这里锁住不回归。"""
        old = tool({**obj(a=STR), "additionalProperties": {"type": "string"}})
        new = tool({**obj(a=STR), "additionalProperties": False})
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("additional_props_closed", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)

    # ---- P0-2: tuple items 长度变化 ----
    def test_tuple_items_longer_is_breaking(self):
        """tuple items 变长 = 新增位置约束，对老数组是收紧。"""
        old = tool(obj(a={"type": "array", "items": [{"type": "string"}]}))
        new = tool(obj(a={"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("items_restricted", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)

    def test_tuple_items_shorter_is_breaking(self):
        """变短已修，回归保护。"""
        old = tool(obj(a={"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}))
        new = tool(obj(a={"type": "array", "items": [{"type": "string"}]}))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("items_restricted", {f.kind for f in found})

    def test_tuple_items_same_length_recurses(self):
        """同长：逐项递归比较（已有逻辑）。"""
        old = tool(obj(a={"type": "array", "items": [{"type": "string"}]}))
        new = tool(obj(a={"type": "array", "items": [{"type": "integer"}]}))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("type_changed", {f.kind for f in found})

    # ---- P0-3: 布尔 schema ----
    def test_boolean_true_to_false_is_breaking(self):
        """true（接受一切）→ false（拒绝一切）= 请求侧收紧。"""
        old = tool(obj(a=True))
        new = tool(obj(a=False))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("schema_rejected", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)

    def test_typed_to_false_is_breaking(self):
        """string → false = 请求侧收紧。"""
        old = tool(obj(a={"type": "string"}))
        new = tool(obj(a=False))
        found = diff_snapshots({"t": old}, {"t": new})
        self.assertIn("schema_rejected", {f.kind for f in found})
        self.assertEqual(worst(found), BREAKING)

    def test_boolean_false_to_true_is_safe(self):
        """false → true = 放宽，不报警。"""
        old = tool(obj(a=False))
        new = tool(obj(a=True))
        self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])

    # ---- P0-5: 响应侧 const / enum 方向 ----
    def test_response_const_removed_is_breaking(self):
        """响应侧 const 消失：老客户端依赖固定值，现在拿不到了 → BREAKING。"""
        old = {"description": "d", "input_schema": {"type": "object", "properties": {}}, "output_schema": obj(v={"type": "string", "const": "ok"})}
        new = {"description": "d", "input_schema": {"type": "object", "properties": {}}, "output_schema": obj(v={"type": "string"})}
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("response_const_removed", kinds)
        self.assertEqual(worst(found), BREAKING)

    def test_response_enum_added_is_risky(self):
        """响应侧 enum 从无到有：老客户端见过任意值，现在被限定 → RISKY（转人工）。"""
        old = {"description": "d", "input_schema": {"type": "object", "properties": {}}, "output_schema": obj(v={"type": "string"})}
        new = {"description": "d", "input_schema": {"type": "object", "properties": {}}, "output_schema": obj(v={"type": "string", "enum": ["a", "b"]})}
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("response_enum_added", kinds)
        self.assertEqual(worst(found), RISKY)

    # ---- P0-7: 已知关键字不比较 ----
    def test_multiple_of_changed_is_risky(self):
        old = tool(obj(n={"type": "integer", "multipleOf": 3}))
        new = tool(obj(n={"type": "integer", "multipleOf": 7}))
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("multiple_of_changed", kinds)
        self.assertEqual(worst(found), RISKY)

    def test_not_branch_changed_is_risky(self):
        old = tool(obj(v={"not": {"type": "string"}}))
        new = tool(obj(v={"not": {"type": "integer"}}))
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("not_changed", kinds)
        self.assertEqual(worst(found), RISKY)

    def test_if_then_changed_is_risky(self):
        old = tool(obj(v={"type": "string", "if": {"minLength": 1}, "then": {"maxLength": 10}}))
        new = tool(obj(v={"type": "string", "if": {"minLength": 1}, "then": {"maxLength": 5}}))
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("if_then_changed", kinds)
        self.assertEqual(worst(found), RISKY)

    def test_contains_changed_is_risky(self):
        old = tool(obj(v={"type": "array", "contains": {"type": "string"}}))
        new = tool(obj(v={"type": "array", "contains": {"type": "integer"}}))
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("contains_changed", kinds)
        self.assertEqual(worst(found), RISKY)

    def test_property_names_changed_is_risky(self):
        old = tool(obj(v={"type": "object", "propertyNames": {"pattern": "^[a-z]+$"}}))
        new = tool(obj(v={"type": "object", "propertyNames": {"pattern": "^[a-z0-9]+$"}}))
        found = diff_snapshots({"t": old}, {"t": new})
        kinds = {f.kind for f in found}
        self.assertIn("property_names_changed", kinds)
        self.assertEqual(worst(found), RISKY)



if __name__ == "__main__":
    unittest.main()
