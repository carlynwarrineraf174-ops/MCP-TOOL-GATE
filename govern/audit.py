import json
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, Index
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from govern.settings import settings
import sys


db_lock = asyncio.Lock() # 全局异步锁

logger = logging.getLogger("govern.proxy.audit")


# 1. 定义 SQLAlchemy 2.0 异步基类
class Base(DeclarativeBase):
    pass


# 2. 定义审计表
class ToolAudit(Base):
    __tablename__ = "tool_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(128))

    # 脱敏三剑客
    args_digest: Mapped[str] = mapped_column(String(64))  # sha256 值
    args_keys: Mapped[str] = mapped_column(Text)  # 只存 key 名字，如 '["order_id"]'
    args_size: Mapped[int] = mapped_column(Integer)  # 参数字节大小

    status: Mapped[str] = mapped_column(String(32))  # ok / rejected / error
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # 👇 加上这段代码
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # 复合索引，满足 "查某租户某工具最近调用" 的需求
    __table_args__ = (
        Index("idx_audit_tenant_tool_time", "tenant", "tool", "created_at"),
    )


# 3. 初始化数据库引擎 (使用 aiosqlite 驱动)
engine = create_async_engine(settings.db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# 4. 建表函数（在启动时代理里调用）
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ================= 核心脱敏与写入逻辑 =================

def digest_args(arguments: dict) -> str:
    """对参数算哈希，保证同参数得出的哈希一致"""
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def mask_keys(arguments: dict) -> str:
    """只提取 key，不存值！"""
    return json.dumps(list(arguments.keys()), ensure_ascii=False)
# 存放后台任务的集合，防止被 Python 垃圾回收
_background_tasks = set()

async def _async_record(tenant: str, tool: str, arguments: dict, status: str, duration_ms: int):
    # 核心：排队写库，杜绝 SQLite 并发锁报错
    async with db_lock:
        try:
            async with AsyncSessionLocal() as session:
                audit = ToolAudit(
                    tenant=tenant,
                    tool=tool,
                    args_digest=digest_args(arguments),
                    args_keys=mask_keys(arguments),
                    args_size=len(json.dumps(arguments).encode()),
                    status=status,
                    duration_ms=duration_ms
                )
                session.add(audit)
                await session.commit()
                print(f"[DB OK] {status}", file=sys.stderr)  # 强烈建议加上这句看结果
        except Exception as e:
            logger.error(f" 审计落库失败: {e}")

def record(tenant: str, tool: str, arguments: dict, status: str, duration_ms: int):
    task = asyncio.create_task(_async_record(tenant, tool, arguments, status, duration_ms))
    _background_tasks.add(task)
    # 任务结束后自动从集合中移除
    task.add_done_callback(_background_tasks.discard)