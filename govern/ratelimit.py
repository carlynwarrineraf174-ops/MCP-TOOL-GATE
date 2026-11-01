import logging
import time
import redis.asyncio as redis
from govern.settings import settings

logger = logging.getLogger("govern.proxy.ratelimit")

# 从 lab_03 抄过来的令牌桶 Lua 脚本，去掉了第一行 #!lua flags=...
TOKEN_BUCKET_LUA = """
local key          = KEYS[1]
local max_tokens   = tonumber(ARGV[1])
local interval     = tonumber(ARGV[2])
local refill_rate  = tonumber(ARGV[3])
local now          = tonumber(ARGV[4])
local increment_by = tonumber(ARGV[5])

local bucket = redis.call("HMGET", key, "refilled_at", "tokens")
local refilled_at
local tokens

if bucket[1] == false then
    refilled_at = now
    tokens = max_tokens
else
    refilled_at = tonumber(bucket[1])
    tokens = tonumber(bucket[2])
end

if now >= refilled_at + interval then
    local num_refills = math.floor((now - refilled_at) / interval)
    tokens = math.min(max_tokens, tokens + num_refills * refill_rate)
    refilled_at = refilled_at + num_refills * interval
end

if tokens < increment_by then
    return {-1, refilled_at + interval}
end

local remaining = tokens - increment_by
local expire_at = math.ceil(((max_tokens - remaining) / refill_rate)) * interval

redis.call("HSET", key, "refilled_at", refilled_at, "tokens", remaining)
redis.call("PEXPIRE", key, expire_at)
return {remaining, refilled_at + interval}
"""


class RateLimiter:
    def __init__(self):
        self.redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.script = self.redis_client.register_script(TOKEN_BUCKET_LUA)

    async def is_allowed(self, tenant_id: str, tool_name: str, rate: int = 1) -> tuple[bool, int]:
        """
        返回 (是否放行, retry_after_ms)。
        - 放行：(True, 0)
        - 拒绝：(False, 距下次可重试的毫秒数)
        - 限流关闭 / fail-open 放行：(True, 0)
        - fail-closed 拒绝：(False, 1000)  # 兜底 1 秒
        """
        if not settings.ratelimit_enabled:
            return True, 0

        now = int(time.time() * 1000)
        key = f"rl:{tenant_id}:{tool_name}"

        try:
            result = await self.script(
                keys=[key],
                args=[
                    settings.ratelimit_burst,
                    settings.ratelimit_interval,
                    settings.ratelimit_rate,
                    now,
                    rate,
                ],
            )
            remaining = result[0]
            if remaining >= 0:
                return True, 0
            # result[1] = 下次可重试的时间戳（毫秒）
            retry_after_ms = max(0, int(result[1]) - now)
            return False, retry_after_ms

        except Exception as e:
            logger.error(f"Redis 限流异常: {e}")
            if settings.ratelimit_fail_mode == "open":
                logger.warning("⚠️ 限流组件异常，根据 fail-open 策略，本次请求放行。")
                return True, 0
            else:
                logger.warning("⚠️ 限流组件异常，根据 fail-closed 策略，本次请求拒绝。")
                return False, 1000