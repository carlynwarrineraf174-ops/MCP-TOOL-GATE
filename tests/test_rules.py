import unittest
import inspect
from gate import diff
from gate.rules import RULES

class RuleConsistencyTest(unittest.TestCase):
    def test_every_rule_has_implementation(self):
        """确保 rules.py 里的每条规则，都在 diff.py 里有对应的 kind 字符串。"""
        source = inspect.getsource(diff)
        missing = []
        for rid, *_ in RULES:
            # 检查 diff.py 源码中是否出现了这个规则 id
            if f'"{rid}"' not in source and f"'{rid}'" not in source:
                missing.append(rid)
        self.assertEqual(missing, [], f"规则表里有，但 diff.py 没实现的规则：{missing}")

if __name__ == "__main__":
    unittest.main()