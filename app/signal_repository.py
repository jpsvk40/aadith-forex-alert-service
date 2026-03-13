"""
Postgres/SQLite persistence for signals.
Dedup key: (pair, timeframe, signal, strategy_version)
A BUY for the same pair+timeframe+strategy_version won't re-fire until
a SELL or HOLD has been logged in between (directional state change).

Incrementing STRATEGY_VERSION in .env resets suppression for all pairs.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, and_, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import settings
from app.strategy import SignalResult

logger = logging.getLogger(__name__)

Base = declarative_base()


class SignalLog(Base):
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    pair = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    signal = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    rsi = Column(Float, nullable=False)
    ema9 = Column(Float, nullable=False)
    ema21 = Column(Float, nullable=False)
    strategy_version = Column(Integer, nullable=False)
    telegram_sent = Column(Integer, default=0)  # 0/1 bool


engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")


def _last_signal(db: Session, pair: str, timeframe: str, strategy_version: int) -> Optional[str]:
    """Return the most recent signal state for this pair+timeframe+strategy_version."""
    row = (
        db.query(SignalLog.signal)
        .filter(
            SignalLog.pair == pair,
            SignalLog.timeframe == timeframe,
            SignalLog.strategy_version == strategy_version,
        )
        .order_by(SignalLog.timestamp.desc())
        .first()
    )
    return row[0] if row else None


def should_suppress(pair: str, timeframe: str, result: SignalResult) -> bool:
    """
    Returns True if this signal should be suppressed (duplicate in same direction).
    HOLD signals are never suppressed, but a logged HOLD resets duplicate suppression.
    """
    if result.signal == "HOLD":
        return False  # always allow HOLD through to DB (for audit), just don't Telegram it
    with SessionLocal() as db:
        last = _last_signal(db, pair, timeframe, result.strategy_version)
        return last == result.signal  # same direction → suppress


def log_signal(
    pair: str,
    timeframe: str,
    result: SignalResult,
    telegram_sent: bool = False,
) -> SignalLog:
    """Persist a signal to the database. Returns the created row."""
    row = SignalLog(
        timestamp=datetime.now(timezone.utc),
        pair=pair,
        timeframe=timeframe,
        signal=result.signal,
        entry_price=result.entry_price,
        rsi=result.rsi,
        ema9=result.ema9,
        ema21=result.ema21,
        strategy_version=result.strategy_version,
        telegram_sent=int(telegram_sent),
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "Logged [%s] %s %s @ %.5f RSI=%.1f",
            row.signal, pair, timeframe, row.entry_price, row.rsi,
        )
        return row


def recent_signals(limit: int = 50) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(SignalLog)
            .order_by(SignalLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [_row_to_dict(r) for r in rows]


def pairs_status() -> list[dict]:
    """Latest signal per pair+timeframe combination."""
    with SessionLocal() as db:
        latest_per_pair = (
            db.query(
                SignalLog.pair.label("pair"),
                SignalLog.timeframe.label("timeframe"),
                func.max(SignalLog.timestamp).label("latest_timestamp"),
            )
            .group_by(SignalLog.pair, SignalLog.timeframe)
            .subquery()
        )

        rows = (
            db.query(SignalLog)
            .join(
                latest_per_pair,
                and_(
                    SignalLog.pair == latest_per_pair.c.pair,
                    SignalLog.timeframe == latest_per_pair.c.timeframe,
                    SignalLog.timestamp == latest_per_pair.c.latest_timestamp,
                ),
            )
            .order_by(SignalLog.pair.asc(), SignalLog.timeframe.asc())
            .all()
        )
        return [_row_to_dict(row) for row in rows]


def alerts_stats() -> dict:
    with SessionLocal() as db:
        total = db.query(SignalLog).count()
        buy = db.query(SignalLog).filter(SignalLog.signal == "BUY").count()
        sell = db.query(SignalLog).filter(SignalLog.signal == "SELL").count()
        sent = db.query(SignalLog).filter(SignalLog.telegram_sent == 1).count()
        return {"total": total, "buy": buy, "sell": sell, "hold": total - buy - sell, "telegram_sent": sent}


def signals_summary() -> list[dict]:
    """
    One row per pair+timeframe: latest signal + indicator snapshot + age in seconds.
    Consumed by the React forex tab.
    """
    now = datetime.now(timezone.utc)
    rows = pairs_status()
    summary_rows = []
    for r in rows:
        ts = r.get("timestamp")
        if ts:
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_seconds = int((now - ts).total_seconds())
        else:
            age_seconds = None

        summary_rows.append({
            "pair": r["pair"],
            "timeframe": r["timeframe"],
            "signal": r["signal"],
            "entry_price": r["entry_price"],
            "rsi": r["rsi"],
            "ema9": r["ema9"],
            "ema21": r["ema21"],
            "timestamp": r.get("timestamp"),
            "age_seconds": age_seconds,
        })
    return summary_rows


def _row_to_dict(row: SignalLog) -> dict:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "pair": row.pair,
        "timeframe": row.timeframe,
        "signal": row.signal,
        "entry_price": row.entry_price,
        "rsi": row.rsi,
        "ema9": row.ema9,
        "ema21": row.ema21,
        "strategy_version": row.strategy_version,
        "telegram_sent": bool(row.telegram_sent),
    }
