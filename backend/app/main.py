"""
FastAPI app entry point.

Run from the backend/ folder:
    uvicorn app.main:app --reload
Then open http://localhost:8000/docs for an interactive list of all endpoints.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import posthog_client, scheduler
from app.alerts import record_posthog_error
from app.config import missing_settings, settings
from app.emailer import email_configured
from app.posthog_client import AnalyticsError
from app.routers import admin, admin_billing, admin_ops, admin_shopify, analytics, auth, billing, client_settings, dashboard, reports, sales

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs once when the server starts, and once when it stops.
    missing = missing_settings()
    if missing:
        raise RuntimeError(
            f"Missing settings in backend/.env: {', '.join(missing)}. See backend/.env.example."
        )
    if not email_configured():
        log.warning("SMTP is not configured: password-reset emails will be printed here instead of sent.")
    await posthog_client.startup()
    posthog_client.error_listeners.append(record_posthog_error)  # PostHog failures become admin alerts
    scheduler.start()  # hourly usage sync, daily health check...
    yield
    scheduler.stop()
    posthog_client.error_listeners.remove(record_posthog_error)
    await posthog_client.shutdown()


app = FastAPI(title="Analytics Portal API", lifespan=lifespan)


@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    """Extra protection against CSRF (another website making your browser send requests
    with your login cookie): requests that CHANGE something must come from our frontend.
    Browsers always send the Origin header on such requests."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.cors_origins:
            return JSONResponse(status_code=403, content={"detail": "Request blocked: unknown origin."})
    return await call_next(request)


# CORS: browsers block a page on localhost:3000 from calling localhost:8000 unless the
# API allows it. allow_credentials lets the browser send the login cookie along.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


# Recording data is several MB of JSON; compressed it shrinks about 10x.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(AnalyticsError)
async def analytics_error_handler(_: Request, exc: AnalyticsError):
    """Friendly, white-label error (no mention of PostHog, no secrets)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    """Anything we did not expect: log it for us, show a generic message to the user."""
    log.exception("Unhandled error: %r", exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_ops.router)
app.include_router(admin_billing.router)
app.include_router(billing.router)
app.include_router(client_settings.router)
app.include_router(reports.router)
app.include_router(sales.router)
app.include_router(dashboard.router)
app.include_router(admin_shopify.router)
app.include_router(analytics.router)
