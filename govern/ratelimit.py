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

    async def is_allowed(self, tenant_id: str, tool_name: str, rate: int = 1) -> bool:
        """
        检查是否允许通过。
        返回 True 放行，False 拦截。
        """
        if not settings.ratelimit_enabled:
            return True

        now = int(time.time() * 1000)
        # key: rl:{tenant}:{tool}
        key = f"rl:{tenant_id}:{tool_name}"

        try:
            # 执行 Lua 脚本
            # 参数含义：max_tokens(桶容量), interval(补充间隔毫秒), refill_rate(每次补多少), now(当前时间), increment_by(消耗多少)
            result = await self.script(
                keys=[key],
                args=[
                    settings.ratelimit_burst,
                    settings.ratelimit_interval,
                    settings.ratelimit_rate,
                    now,
                    rate
                ]
            )
            remaining = result[0]
            return remaining >= 0

        except Exception as e:
            logger.error(f"Redis 限流异常: {e}")
            # 降级策略（fail-open 或 fail-closed）
            if settings.ratelimit_fail_mode == "open":
                logger.warning("⚠️ 限流组件异常，根据 fail-open 策略，本次请求放行。")
                return True
            else:
                logger.warning("⚠️ 限流组件异常，根据 fail-closed 策略，本次请求拒绝。")
                return False