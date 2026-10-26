import limiter


def test_burst_then_denied_with_exact_headers_math():
    t = 1000.0
    for i in range(10):
        assert limiter._consume_memory("k", 10, 60, now=t) == (True, 9 - i, 0, (i + 1) * 6)
    assert limiter._consume_memory("k", 10, 60, now=t) == (False, 0, 6, 60)


def test_refill_one_token_then_full():
    t = 1000.0
    for _ in range(10):
        limiter._consume_memory("k", 10, 60, now=t)
    assert limiter._consume_memory("k", 10, 60, now=t + 6.001)[0] is True
    assert limiter._consume_memory("k", 10, 60, now=t + 66.002) == (True, 9, 0, 6)


def test_keys_are_independent():
    t = 1000.0
    for _ in range(10):
        limiter._consume_memory("a", 10, 60, now=t)
    assert limiter._consume_memory("a", 10, 60, now=t)[0] is False
    assert limiter._consume_memory("b", 10, 60, now=t) == (True, 9, 0, 6)


def test_sweep_evicts_idle_full_buckets():
    limiter._buckets["idle"] = [9.0, 1000.0, 10.0, 60.0]
    limiter._sweep(2000.0)
    assert "idle" not in limiter._buckets


def test_sweep_keeps_active_buckets():
    limiter._buckets["hot"] = [9.0, 1000.0, 10.0, 60.0]
    limiter._sweep(1030.0)
    assert "hot" in limiter._buckets
