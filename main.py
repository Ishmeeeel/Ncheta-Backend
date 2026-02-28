"""
Ncheta Backend — FastAPI Application
=====================================
Run locally:
  uvicorn main:app --reload --port 8000

Environment variables:
  Copy .env.example to .env and fill in all values.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from routers import auth, student, teacher, admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s — %(message)s")

# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title        = "Ncheta API",
    description  = "AI-powered accessible education platform for Nigeria",
    version      = "1.0.0",
    docs_url     = "/docs",
    redoc_url    = "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────
# Allow the Next.js frontend and Vercel preview URLs

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "https://ncheta.vercel.app",
        "https://*.vercel.app",
    ],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(admin.router)

# ── Health & root ─────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "Ncheta API", "version": "1.0.0"}


@app.get("/health", tags=["health"])
async def health():
    """Render pings this to check the service is alive."""
    return {"status": "ok"}
