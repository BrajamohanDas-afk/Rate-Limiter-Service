import pytest

import limiter
import main


@pytest.fixture(autouse=True)
def _isolate():
    # ponytail: tests reset module internals directly; fine at this size.
    limiter._buckets.clear()
    main.IP_LIMIT = (10_000, 60)
    yield
