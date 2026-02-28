"""
Ncheta FastAPI Backend
=======================
Entry point. Registers all routers, configures CORS, adds health check.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import auth, student, teacher, admin

app = FastAPI(
    title="Ncheta API",
    description="Backend for the Ncheta accessible education platform",
    version="1.0.0",
    docs_url="/docs",       # Swagger UI at /docs
    redoc_url="/redoc",     # ReDoc at /redoc
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow requests from the Next.js frontend (local dev + Vercel production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,          # e.g. http://localhost:3000
        "https://ncheta.vercel.app",    # Update to your actual Vercel URL
        "https://*.vercel.app",         # Vercel preview deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(admin.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["health"])
async def root():
    return {
        "status":  "ok",
        "service": "Ncheta API",
        "version": "1.0.0",
    }


@app.get("/health", tags=["health"])
async def health():
    """Render uses this to check if the server is alive."""
    return {"status": "healthy"}
