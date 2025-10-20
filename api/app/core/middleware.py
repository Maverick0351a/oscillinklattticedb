"""HTTP middlewares for protections and headers.

Separated to keep app assembly in main.py slim and readable.

Note for tests/back-compat:
- Expose module-level globals and functions so callers can import/patch
    rate limiting and concurrency state via ``app.main`` re-exports.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable
from contextlib import suppress

from fastapi import Request, status
from fastapi.responses import JSONResponse

from .config import settings
from .metrics import REQ_RATELIMITED, REQ_OVERLOADS, REQ_TIMEOUTS

## --- Module-level state for tests and back-compat ---
RL_STATE: dict[tuple[str, str], tuple[int, int]] = {}
SEM: asyncio.Semaphore | None = None
SEM_MAX: int | None = None


async def size_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    cl = request.headers.get("content-length")
    try:
        if cl is not None and int(cl) > settings.max_request_bytes:
            # In function-based middleware, prefer returning a response rather than raising,
            # to avoid bubbling an unhandled exception that becomes a 500 in some setups.
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "request too large"},
            )
    except ValueError:
        pass
    return await call_next(request)


async def rate_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    if not settings.rate_limit_enabled:
        return await call_next(request)

    client = "unknown"
    try:
        if settings.trust_x_forwarded_for:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                client = xff.split(",")[0].strip() or client
        if client == "unknown":
            client = request.client.host if request.client else "unknown"
    except Exception:
        client = "unknown"
    path = request.url.path
    import time as _time
    now = int(_time.time())
    period = max(1, int(settings.rate_limit_period_seconds))
    window_start = now - (now % period)

    if settings.rate_limit_redis_url:
        try:
            import redis  # type: ignore

            r = redis.StrictRedis.from_url(settings.rate_limit_redis_url)
            key = f"rl:{client}:{path}:{window_start}"
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, period + 1)
            cnt, _ = pipe.execute()
            if int(cnt) > int(settings.rate_limit_requests):
                try:
                    REQ_RATELIMITED.labels(path=path).inc()
                except Exception:
                    pass
                return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "rate limit exceeded"})
        except Exception:
            # Fallback to in-memory on any error
            pass

    key_mem = (client, path)
    old = RL_STATE.get(key_mem)
    if old and old[0] == window_start:
        count = old[1]
    else:
        count = 0
    if count >= int(settings.rate_limit_requests):
        try:
            REQ_RATELIMITED.labels(path=path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "rate limit exceeded"})
    RL_STATE[key_mem] = (window_start, count + 1)
    return await call_next(request)


async def security_headers_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if settings.enable_hsts:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    rid = request.headers.get("x-request-id")
    if not rid:
        import uuid

        rid = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


async def concurrency_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    global SEM, SEM_MAX
    max_c = int(settings.max_concurrency)
    if max_c <= 0:
        return await call_next(request)
    if SEM is None or SEM_MAX != max_c:
        SEM = asyncio.Semaphore(max_c)
        SEM_MAX = max_c
    # Try a non-blocking acquire using a cancellable task and a tiny timeout.
    acquired = False
    acq_task = asyncio.create_task(SEM.acquire())
    try:
        # Use zero-timeout to preserve existing test behavior while avoiding warnings by
        # cancelling the pending task on timeout.
        await asyncio.wait_for(acq_task, timeout=0)
        acquired = True
    except asyncio.TimeoutError:
        acq_task.cancel()
        with suppress(asyncio.CancelledError):
            await acq_task
        try:
            REQ_OVERLOADS.labels(path=request.url.path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "server overloaded"})
    try:
        return await call_next(request)
    finally:
        try:
            if acquired and SEM is not None:
                SEM.release()
        except Exception:
            # Swallow release errors
            pass


async def timeout_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    tmo = float(settings.request_timeout_seconds)
    if tmo <= 0:
        return await call_next(request)
    try:
        return await asyncio.wait_for(call_next(request), timeout=tmo)
    except asyncio.TimeoutError:
        try:
            REQ_TIMEOUTS.labels(path=request.url.path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=504, content={"detail": "request timeout"})


def install_http_middlewares(app) -> None:
    """Register non-metrics middlewares onto the FastAPI app in a defined order."""
    app.middleware("http")(size_limit_middleware)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(security_headers_middleware)
    app.middleware("http")(request_id_middleware)
    app.middleware("http")(concurrency_middleware)
    app.middleware("http")(timeout_middleware)
