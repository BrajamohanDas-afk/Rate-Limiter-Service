import math
import os
import time

TIERS = {
    "free": (10, 60),    # (capacity/burst, window seconds)
    "pro": (100, 60),
}

_USE_REDIS = os.getenv("REDIS_URL")
if _USE_REDIS:
    import redis

    _client = redis.from_url(_USE_REDIS)

    # Atomic token bucket. 2x-window TTL doubles as eviction for idle keys.
    # KEYS[1] = bucket key; ARGV: capacity, rate (tokens/sec), cost, window (sec)
    _LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
local now = tonumber(redis.call('TIME')[1]) + tonumber(redis.call('TIME')[2]) / 1000000
local stored = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(stored[1])
local ts = tonumber(stored[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now end
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], window * 2)
return {allowed, tostring(tokens)}
"""

    # ponytail: sync redis call inside async handlers; redis.asyncio if throughput ever matters.
    def _consume_redis(key, capacity, window, cost=1):
        rate = capacity / window
        allowed, tokens = _client.eval(_LUA, 1, f"rl:{key}", capacity, rate, cost, window)
        tokens = float(tokens)
        remaining = int(tokens)
        if allowed:
            return True, remaining, 0, math.ceil((capacity - tokens) * window / capacity)
        retry = math.ceil((cost - tokens) * window / capacity)
        return False, remaining, retry, math.ceil((capacity - tokens) * window / capacity)


_buckets: dict[str, list[float]] = {}
_writes = 0


def _sweep(now):
    # ponytail: amortized sweep (every 1000 writes), no background task; Redis backend gets TTL eviction for free.
    for k, (tokens, ts, capacity, window) in list(_buckets.items()):
        full_at = ts + (capacity - tokens) * window / capacity
        if now > full_at + window:
            del _buckets[k]


def _consume_memory(key, capacity, window, cost=1, now=None):
    global _writes
    now = time.monotonic() if now is None else now
    rate = capacity / window
    state = _buckets.get(key)
    if state is None:
        state = _buckets[key] = [float(capacity), now, float(capacity), float(window)]
    tokens = min(capacity, state[0] + (now - state[1]) * rate)
    state[0], state[1] = tokens, now
    allowed = tokens >= cost
    if allowed:
        state[0] = tokens - cost
    _writes += 1
    if _writes % 1000 == 0:
        _sweep(now)
    tokens = state[0]
    remaining = int(tokens)
    if allowed:
        return True, remaining, 0, math.ceil((capacity - tokens) * window / capacity)
    retry = math.ceil((cost - tokens) * window / capacity)
    return False, remaining, retry, math.ceil((capacity - tokens) * window / capacity)


def check(key, capacity, window, cost=1, now=None):
    """Returns (allowed, remaining, retry_after_seconds, reset_seconds).

    `now` is only honoured by the in-memory backend (Redis uses its own server clock).
    """
    if _USE_REDIS:
        return _consume_redis(key, capacity, window, cost)
    return _consume_memory(key, capacity, window, cost, now)


if __name__ == "__main__":
    t = 1000.0
    for i in range(10):
        result = _consume_memory("u", 10, 60, now=t)
        assert result == (True, 9 - i, 0, (i + 1) * 6), (i, result)
    result = _consume_memory("u", 10, 60, now=t)
    assert result == (False, 0, 6, 60), result
    assert _consume_memory("v", 10, 60, now=t) == (True, 9, 0, 6)
    assert _consume_memory("u", 10, 60, now=t + 6.001)[0] is True
    assert _consume_memory("w", 10, 60, now=t)[0] is True
    result = _consume_memory("w", 10, 60, now=t + 60.001)
    assert result == (True, 9, 0, 6), result
    _writes = 999
    _consume_memory("live", 10, 60, now=t + 2000.0)
    assert "u" not in _buckets and "v" not in _buckets and "w" not in _buckets, sorted(_buckets)
    assert "live" in _buckets
    print("limiter self-check ok")
