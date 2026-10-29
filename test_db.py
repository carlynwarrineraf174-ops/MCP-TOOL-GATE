import sqlite3
conn = sqlite3.connect("govern_v2.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("存在的表:", cursor.fetchall())

cursor.execute("SELECT count(*) FROM tool_audit;")
print("tool_audit 数据条数:", cursor.fetchone()[0])