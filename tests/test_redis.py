import os
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL not set")


def test_redis_token_bucket_roundtrip():
    import limiter

    assert limiter._USE_REDIS
    key = f"test-{uuid.uuid4()}"
    for _ in range(3):
        assert limiter.check(key, 3, 2)[0] is True
    allowed, remaining, retry, reset = limiter.check(key, 3, 2)
    assert allowed is False
    assert remaining == 0
    assert 1 <= retry <= 2
    time.sleep(2.1)
    assert limiter.check(key, 3, 2)[0] is True
