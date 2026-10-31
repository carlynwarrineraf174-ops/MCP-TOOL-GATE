import sqlite3
conn = sqlite3.connect("govern.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("存在的表:", cursor.fetchall())

cursor.execute("SELECT count(*) FROM tool_audit;")
print("tool_audit 数据条数:", cursor.fetchone()[0])

# import sqlite3
#
# conn = sqlite3.connect("govern.db")
# cursor = conn.cursor()
#
# # 执行删除
# cursor.execute("DELETE FROM tool_audit WHERE id > ?", (0,))
#
# # 提交事务（必须！否则不生效）
# conn.commit()
#
# print(f"删除了 {cursor.rowcount} 条记录")
#
# conn.close()