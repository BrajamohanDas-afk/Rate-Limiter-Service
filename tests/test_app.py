from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)

FREE = {"X-API-Key": "free-demo-key"}
PRO = {"X-API-Key": "pro-demo-key"}
ADMIN = {"X-API-Key": "admin-demo-key"}


def test_missing_api_key_is_401():
    assert client.post("/check-limit", json={"key": "k"}).status_code == 401


def test_bad_api_key_is_401():
    assert client.post("/check-limit", json={"key": "k"}, headers={"X-API-Key": "nope"}).status_code == 401


def test_missing_body_key_is_422():
    assert client.post("/check-limit", json={}, headers=FREE).status_code == 422


def test_free_tier_burst_headers_and_429():
    for i in range(10):
        r = client.post("/check-limit", json={"key": "burst"}, headers=FREE)
        assert r.status_code == 200
        assert r.json() == {"status": "Allowed", "tier": "free"}
        assert r.headers["X-RateLimit-Limit"] == "10"
        assert r.headers["X-RateLimit-Remaining"] == str(9 - i)
    r = client.post("/check-limit", json={"key": "burst"}, headers=FREE)
    assert r.status_code == 429
    body = r.json()
    assert body["status"] == "Rate limit exceeded"
    assert body["tier"] == "free"
    assert 1 <= body["retryAfter"] <= 6
    assert r.headers["Retry-After"] == str(body["retryAfter"])
    assert r.headers["X-RateLimit-Remaining"] == "0"
    assert r.headers["X-RateLimit-Reset"] == "60"


def test_target_keys_are_independent():
    for _ in range(10):
        client.post("/check-limit", json={"key": "a"}, headers=FREE)
    assert client.post("/check-limit", json={"key": "a"}, headers=FREE).status_code == 429
    assert client.post("/check-limit", json={"key": "b"}, headers=FREE).status_code == 200


def test_pro_tier_allows_100():
    for _ in range(100):
        assert client.post("/check-limit", json={"key": "pro"}, headers=PRO).status_code == 200
    r = client.post("/check-limit", json={"key": "pro"}, headers=PRO)
    assert r.status_code == 429
    assert r.headers["X-RateLimit-Limit"] == "100"


def test_admin_tier_is_unlimited_and_headerless():
    for _ in range(50):
        r = client.post("/check-limit", json={"key": "adm"}, headers=ADMIN)
        assert r.status_code == 200
        assert r.json() == {"status": "Allowed", "tier": "admin"}
        assert "X-RateLimit-Limit" not in r.headers


def test_ip_middleware_denies_with_scope(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT", (3, 60))
    for _ in range(3):
        assert client.post("/check-limit", json={"key": "x"}, headers=ADMIN).status_code == 200
    r = client.post("/check-limit", json={"key": "x"}, headers=ADMIN)
    assert r.status_code == 429
    assert r.json()["scope"] == "ip"
    assert "Retry-After" in r.headers


def test_frontend_is_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Rate Limiter" in r.text


def test_metrics_endpoint():
    client.post("/check-limit", json={"key": "metrics"}, headers=FREE)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "ratelimit_allowed_total" in r.text
