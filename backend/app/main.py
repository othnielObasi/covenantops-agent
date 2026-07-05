"""CovenantOps Agent FastAPI application entrypoint.

This application is built on the CovenantOps Agent codebase.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router

app = FastAPI(
    title="CovenantOps Agent",
    description="Vultr-ready verifiable covenant-monitoring agent.",
    version="0.1.0",
)

_origins = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def root_health():
    return {"status": "ok", "service": "covenantops-agent", "base": "covenantops"}
