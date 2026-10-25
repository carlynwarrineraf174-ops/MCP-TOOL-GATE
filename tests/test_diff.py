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

    # def test_dependent_required_added_is_breaking(self):
    #     old = tool({"type": "object", "properties": {"card": STR, "addr": STR}})
    #     new = tool({"type": "object", "properties": {"card": STR, "addr": STR},
    #                 "dependentRequired": {"card": ["addr"]}})
    #     found = diff_snapshots({"t": old}, {"t": new})
    #     self.assertIn("dependent_required_added", {x.kind for x in found})
    #     self.assertEqual(worst(found), BREAKING)
    #
    # def test_dependent_required_removed_is_safe(self):
    #     old = tool({"type": "object", "properties": {"card": STR, "addr": STR},
    #                 "dependentRequired": {"card": ["addr"]}})
    #     new = tool({"type": "object", "properties": {"card": STR, "addr": STR}})
    #     self.assertEqual(diff_snapshots({"t": old}, {"t": new}), [])
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




if __name__ == "__main__":
    unittest.main()
