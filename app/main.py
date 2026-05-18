"""
AtomQuest Goal Tracking Portal — Main Application
FastAPI + SQLite (WAL) + Jinja2 + Bootstrap 5
Handles 1,000s of users via connection pooling, WAL mode, and GZip compression.
"""
from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import time

from .database import engine, Base, SessionLocal
from . import models
from .routers import auth, employee, manager, admin, reports, analytics
from .services.escalation import run_escalation_checks
from .template_utils import Templates

logger = logging.getLogger(__name__)

# ── Jinja2 templates (used only for error pages at app level) ─────────────────
templates = Templates(directory="app/templates")


def run_escalation_job():
    db = SessionLocal()
    try:
        run_escalation_checks(db)
        logger.info("Escalation check completed.")
    except Exception as exc:
        logger.error("Escalation job error: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    Base.metadata.create_all(bind=engine)

    # Start escalation scheduler
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(run_escalation_job, "interval", hours=24, id="escalation_check",
                      misfire_grace_time=3600)
    scheduler.start()
    logger.info("Application started. Escalation scheduler running.")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Application shutdown.")


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="AtomQuest Goal Portal",
    description="In-House Goal Setting & Tracking Portal — Atomberg",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=500)  # compress responses > 500 bytes

# ── Static Files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(employee.router)
app.include_router(manager.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(analytics.router)


# ── Root redirect ─────────────────────────────────────────────────────────────
@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login")


# ── Request timing middleware (dev/debug) ────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"
    return response


# ── Global error handlers ────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    # If it's an API call, return JSON; otherwise return HTML
    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        from .auth import get_current_user_from_cookie
        from .database import SessionLocal
        db = SessionLocal()
        user = get_current_user_from_cookie(request, db)
        db.close()
        return templates.TemplateResponse(request, "errors/404.html",
                                          {"request": request, "user": user,
                                           "unread_count": 0}, status_code=404)
    except Exception:
        pass
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login", status_code=302)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    logger.error("500 error on %s: %s", request.url, exc)
    return JSONResponse(
        {"error": "Internal server error. Please try again."},
        status_code=500
    )


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["monitoring"])
def health_check():
    """Quick health check endpoint for load balancers / uptime monitors."""
    from .database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse({"status": "error", "db": str(e)}, status_code=503)
    finally:
        db.close()
