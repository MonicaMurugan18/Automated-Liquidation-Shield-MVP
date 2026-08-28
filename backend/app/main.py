"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import API_VERSION, router
from .config import get_settings
from .models.domain import ValidationError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=API_VERSION,
    description=(
        "Autonomous DeFi liquidation protection. All blockchain interaction in "
        "this build is SIMULATED -- no transaction is ever signed or broadcast."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValidationError)
async def domain_validation_handler(_: Request, exc: ValidationError) -> JSONResponse:
    """Any domain rule that escapes a route handler still returns a clean 422.

    Edge case 8 is enforced in the engine, so this net catches it wherever it
    is raised rather than relying on every route remembering to try/except.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "error_type": "validation_error"},
    )


app.include_router(router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": API_VERSION,
        "docs": "/docs",
        "api": settings.api_prefix,
        "blockchain": "simulated",
    }
