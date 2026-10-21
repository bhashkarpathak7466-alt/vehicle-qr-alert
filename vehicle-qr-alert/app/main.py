"""
App entry point.

Plain-language summary:
This file creates the FastAPI app object and wires in the routers
(the actual API endpoints, defined in app/routers/). Keeping this
file thin -- no business logic here -- is what makes the project
"modular": each router owns its own slice of the app.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.session import Base, engine

# Import models so SQLAlchemy knows about every table before
# create_all() runs.
from app.models import user, vehicle, alert  # noqa: F401

from app.routers import auth, vehicles, alerts, web

app = FastAPI(title=settings.APP_NAME)

# JSON API routers
app.include_router(auth.router)
app.include_router(vehicles.router)
app.include_router(alerts.router)

# HTML page routes (the actual browsable web app)
app.include_router(web.router)

# CSS/JS/images referenced by the templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# In a real production setup we'd use Alembic migrations instead of
# create_all(). For this project, create_all() is enough and keeps
# the "run it in 30 seconds" setup story simple -- a deliberate
# trade-off worth mentioning in an interview.
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    """Basic liveness check -- confirms the app booted and can respond."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}


@app.get("/health/ai")
def ai_health_check():
    """
    Diagnostic endpoint: tells you WITHOUT submitting a report whether
    the real vision-AI authenticity check will actually run, or whether
    every report will silently fall back to the rule-based heuristic.

    Visit http://localhost:8000/health/ai in a browser after setting
    AI_ENABLED=true + AI_PROVIDER + AI_API_KEY in .env to confirm the
    setup worked. NOTE: this only checks config/package presence -- it
    cannot detect provider-side issues like Anthropic billing credits
    running out or a Gemini free-tier quota being hit. Submit an
    actual test report and watch the terminal log for that.
    """
    provider = (settings.AI_PROVIDER or "anthropic").lower()
    key_configured = bool(settings.AI_API_KEY)

    package_ok = True
    package_note = "httpx (already installed) -- no extra package needed for Gemini"
    if provider == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            package_ok = False
        package_note = "anthropic package"

    will_use_real_ai = settings.AI_ENABLED and key_configured and package_ok and provider in ("anthropic", "gemini")

    reasons = []
    if not settings.AI_ENABLED:
        reasons.append("AI_ENABLED is false in .env -- set it to true")
    if provider not in ("anthropic", "gemini"):
        reasons.append(f"AI_PROVIDER={provider!r} is not recognized -- use 'anthropic' or 'gemini'")
    if not key_configured:
        reasons.append("AI_API_KEY is empty in .env -- paste your real key for the chosen provider")
    if not package_ok:
        reasons.append("`anthropic` package not installed -- run: pip install -r requirements-ai.txt")

    return {
        "AI_ENABLED_in_config": settings.AI_ENABLED,
        "provider": provider,
        "api_key_configured": key_configured,
        "package_required": package_note,
        "package_installed": package_ok,
        "will_real_ai_run_on_next_report": will_use_real_ai,
        "if_false_because": reasons or ["nothing -- real AI should run"],
    }
