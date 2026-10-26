import json
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from limiter import TIERS, check

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rate_limiter")

# ponytail: demo keys baked in; override with API_KEYS env (JSON) for anything real.
API_KEYS = json.loads(os.getenv("API_KEYS", '{"free-demo-key": "free", "pro-demo-key": "pro", "admin-demo-key": "admin"}'))
IP_LIMIT = (100, 60)  # per-IP global limit: capacity, window seconds

ALLOWED = Counter("ratelimit_allowed_total", "Allowed checks", ["tier"])
DENIED = Counter("ratelimit_denied_total", "Denied checks", ["tier"])
IP_DENIED = Counter("ratelimit_ip_denied_total", "Requests denied by per-IP middleware")

app = FastAPI(title="Rate Limiter Service")


@app.middleware("http")
async def limit_by_ip(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    allowed, _, retry_after, _ = check(f"ip:{ip}", *IP_LIMIT)
    if not allowed:
        IP_DENIED.inc()
        logger.info("ip denied ip=%s retry_after=%ss", ip, retry_after)
        return JSONResponse(
            {"status": "Rate limit exceeded", "scope": "ip", "retryAfter": retry_after},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


def current_tier(x_api_key: str | None = Header(None)) -> str:
    tier = API_KEYS.get(x_api_key) if x_api_key else None
    if tier is None:
        raise HTTPException(401, "Missing or invalid X-API-Key")
    return tier


class CheckRequest(BaseModel):
    key: str


@app.post("/check-limit")
async def check_limit(body: CheckRequest, tier: str = Depends(current_tier)):
    limits = TIERS.get(tier)
    if limits is None:  # admin: unlimited
        ALLOWED.labels(tier).inc()
        return {"status": "Allowed", "tier": tier}
    allowed, remaining, retry_after, reset = check(body.key, *limits)
    headers = {
        "X-RateLimit-Limit": str(limits[0]),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }
    if allowed:
        ALLOWED.labels(tier).inc()
        return JSONResponse({"status": "Allowed", "tier": tier}, headers=headers)
    DENIED.labels(tier).inc()
    logger.info("denied key=%s tier=%s retry_after=%ss", body.key, tier, retry_after)
    headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        {"status": "Rate limit exceeded", "tier": tier, "retryAfter": retry_after},
        status_code=429,
        headers=headers,
    )


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
