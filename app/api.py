"""
FastAPI service — read-only endpoints for external consumers (React forex tab, monitoring).
Run alongside the scheduler via main.py.
"""

from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app.signal_repository import (
    recent_signals,
    pairs_status,
    alerts_stats,
    signals_summary,
)
from app.data_provider import check_provider_health

app = FastAPI(title="Forex Alert Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to stock dashboard origin in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

_start_time = datetime.now(timezone.utc)


# ── Response models ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: int
    timestamp: str


class SignalItem(BaseModel):
    id: Optional[int]
    timestamp: Optional[str]
    pair: str
    timeframe: str
    signal: str
    entry_price: float
    rsi: float
    ema9: float
    ema21: float
    strategy_version: int
    telegram_sent: bool


class SummaryItem(BaseModel):
    pair: str
    timeframe: str
    signal: str
    entry_price: float
    rsi: float
    ema9: float
    ema21: float
    timestamp: Optional[str]
    age_seconds: Optional[int]


class ProviderStatus(BaseModel):
    status: str
    provider: str
    last_fetch_utc: Optional[str]
    error: Optional[str]


class RootResponse(BaseModel):
    service: str
    status: str
    docs_url: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", response_model=RootResponse)
def root():
    return RootResponse(
        service="forex-alert-service",
        status="ok",
        docs_url="/docs",
    )


@app.get("/health", response_model=HealthResponse)
def health():
    uptime = int((datetime.now(timezone.utc) - _start_time).total_seconds())
    return HealthResponse(
        status="ok",
        uptime_seconds=uptime,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/signals/recent")
def get_recent_signals(limit: int = 50):
    return recent_signals(limit=limit)


@app.get("/signals/summary")
def get_signals_summary():
    """
    One row per pair+timeframe: latest signal, indicator snapshot, age in seconds.
    Primary endpoint consumed by the React forex tab.
    """
    return signals_summary()


@app.get("/pairs/status")
def get_pairs_status():
    return pairs_status()


@app.get("/alerts/stats")
def get_alerts_stats():
    return alerts_stats()


@app.get("/providers/status", response_model=ProviderStatus)
def get_providers_status():
    """
    Twelve Data connectivity check — last successful fetch + error if any.
    Separate from /health: /health = is this service up, /providers/status = is data flowing.
    """
    return check_provider_health()
