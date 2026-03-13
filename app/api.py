"""
FastAPI service — read-only endpoints for external consumers (React forex tab, monitoring).
Run alongside the scheduler via main.py.
"""

from datetime import datetime, timezone
from datetime import date as date_type
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app.signal_repository import (
    recent_signals,
    pairs_status,
    alerts_stats,
    signals_summary,
    performance_daily,
    performance_summary,
    performance_by_pair,
    performance_by_timeframe,
)
from app.data_provider import check_provider_health
from app.reporting import daily_report_preview, send_daily_report

app = FastAPI(title="Forex Alert Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to stock dashboard origin in production
    allow_methods=["GET", "POST"],
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


class PerformanceDailyResponse(BaseModel):
    date: str
    total_signals: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    telegram_sent: int
    resolved_signals: int
    wins: int
    losses: int
    expired: int
    neutral: int
    open_signals: int
    win_rate: Optional[float]
    avg_return_pct: Optional[float]


class PerformanceSummaryResponse(PerformanceDailyResponse):
    range: dict
    best_pair: Optional[str]
    worst_pair: Optional[str]
    best_timeframe: Optional[str]
    worst_timeframe: Optional[str]


class PerformanceGroupItem(BaseModel):
    total_signals: int
    resolved_signals: int
    wins: int
    losses: int
    win_rate: Optional[float]
    avg_return_pct: Optional[float]
    pair: Optional[str] = None
    timeframe: Optional[str] = None


class DailyReportPreviewResponse(BaseModel):
    date: str
    headline: str
    summary_lines: list[str]
    metrics: PerformanceDailyResponse


class DailyReportSendResponse(BaseModel):
    ok: bool
    date: str
    sent_to: str


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


@app.get("/performance/daily", response_model=PerformanceDailyResponse)
def get_performance_daily(date: Optional[date_type] = None):
    return performance_daily(date)


@app.get("/performance/summary", response_model=PerformanceSummaryResponse)
def get_performance_summary(
    from_date: Optional[date_type] = None,
    to_date: Optional[date_type] = None,
):
    today = datetime.now(timezone.utc).date()
    start = from_date or today
    end = to_date or today
    return performance_summary(start, end)


@app.get("/performance/by-pair")
def get_performance_by_pair(
    from_date: Optional[date_type] = None,
    to_date: Optional[date_type] = None,
):
    today = datetime.now(timezone.utc).date()
    start = from_date or today
    end = to_date or today
    return {"items": performance_by_pair(start, end)}


@app.get("/performance/by-timeframe")
def get_performance_by_timeframe(
    from_date: Optional[date_type] = None,
    to_date: Optional[date_type] = None,
):
    today = datetime.now(timezone.utc).date()
    start = from_date or today
    end = to_date or today
    return {"items": performance_by_timeframe(start, end)}


@app.get("/reports/daily/preview", response_model=DailyReportPreviewResponse)
def get_daily_report_preview(date: Optional[date_type] = None):
    return daily_report_preview(date)


@app.post("/reports/daily/send", response_model=DailyReportSendResponse)
def post_daily_report_send(date: Optional[date_type] = None):
    target = date or datetime.now(timezone.utc).date()
    return DailyReportSendResponse(
        ok=send_daily_report(target),
        date=target.isoformat(),
        sent_to="telegram",
    )
