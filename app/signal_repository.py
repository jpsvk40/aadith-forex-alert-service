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
    create_engine, Column, Integer, String, Float, DateTime, text
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
    """Return the most recent non-HOLD signal for this pair+timeframe+strategy_version."""
    row = (
        db.query(SignalLog.signal)
        .filter(
            SignalLog.pair == pair,
            SignalLog.timeframe == timeframe,
            SignalLog.strategy_version == strategy_version,
            SignalLog.signal != "HOLD",
        )
        .order_by(SignalLog.timestamp.desc())
        .first()
    )
    return row[0] if row else None


def should_suppress(pair: str, timeframe: str, result: SignalResult) -> bool:
    """
    Returns True if this signal should be suppressed (duplicate in same direction).
    HOLD signals are never suppressed but are also not used as dedup anchors.
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
        result = db.execute(text("""
            SELECT DISTINCT ON (pair, timeframe)
                pair, timeframe, signal, entry_price, rsi, ema9, ema21, timestamp
            FROM signal_logs
            ORDER BY pair, timeframe, timestamp DESC
        """)).mappings().all()
        return [dict(r) for r in result]


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
    from datetime import datetime, timezone as tz
    now = datetime.now(timezone.utc)
    rows = pairs_status()
    for r in rows:
        ts = r.get("timestamp")
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            r["age_seconds"] = int((now - ts).total_seconds())
        else:
            r["age_seconds"] = None
    return rows


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
