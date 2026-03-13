"""
Postgres/SQLite persistence for signals.
Dedup key: (pair, timeframe, signal, strategy_version)
A BUY for the same pair+timeframe+strategy_version won't re-fire until
a SELL or HOLD has been logged in between (directional state change).

Incrementing STRATEGY_VERSION in .env resets suppression for all pairs.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
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


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_log_id = Column(Integer, nullable=False, unique=True)
    pair = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    signal = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_timestamp = Column(DateTime(timezone=True), nullable=False)
    exit_price = Column(Float, nullable=True)
    exit_timestamp = Column(DateTime(timezone=True), nullable=True)
    outcome = Column(String(10), nullable=True)
    return_pct = Column(Float, nullable=True)
    bars_held = Column(Integer, nullable=True)
    evaluation_rule = Column(String(50), nullable=False)
    strategy_version = Column(Integer, nullable=False)
    status = Column(String(10), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


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


def create_signal_outcome(signal_log: SignalLog, evaluation_bars: int) -> None:
    if signal_log.signal not in {"BUY", "SELL"}:
        return

    now = datetime.now(timezone.utc)
    rule = f"fixed_bars:{evaluation_bars}"
    with SessionLocal() as db:
        existing = (
            db.query(SignalOutcome.id)
            .filter(SignalOutcome.signal_log_id == signal_log.id)
            .first()
        )
        if existing:
            return

        outcome = SignalOutcome(
            signal_log_id=signal_log.id,
            pair=signal_log.pair,
            timeframe=signal_log.timeframe,
            signal=signal_log.signal,
            entry_price=signal_log.entry_price,
            entry_timestamp=signal_log.timestamp,
            exit_price=None,
            exit_timestamp=None,
            outcome=None,
            return_pct=None,
            bars_held=None,
            evaluation_rule=rule,
            strategy_version=signal_log.strategy_version,
            status="open",
            created_at=now,
            updated_at=now,
        )
        db.add(outcome)
        db.commit()


def open_outcomes() -> list[SignalOutcome]:
    with SessionLocal() as db:
        return (
            db.query(SignalOutcome)
            .filter(SignalOutcome.status == "open")
            .order_by(SignalOutcome.entry_timestamp.asc())
            .all()
        )


def resolve_signal_outcome(
    outcome_id: int,
    exit_price: float,
    exit_timestamp: datetime,
    bars_held: int,
) -> Optional[dict]:
    with SessionLocal() as db:
        row = db.query(SignalOutcome).filter(SignalOutcome.id == outcome_id).first()
        if not row or row.status != "open":
            return None

        if row.signal == "BUY":
            return_pct = ((exit_price - row.entry_price) / row.entry_price) * 100
        else:
            return_pct = ((row.entry_price - exit_price) / row.entry_price) * 100

        if return_pct > 0:
            outcome_value = "win"
        elif return_pct < 0:
            outcome_value = "loss"
        else:
            outcome_value = "neutral"

        row.exit_price = exit_price
        row.exit_timestamp = exit_timestamp
        row.outcome = outcome_value
        row.return_pct = return_pct
        row.bars_held = bars_held
        row.status = "resolved"
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "pair": row.pair,
            "timeframe": row.timeframe,
            "signal": row.signal,
            "entry_price": row.entry_price,
            "exit_price": row.exit_price,
            "outcome": row.outcome,
            "return_pct": row.return_pct,
            "bars_held": row.bars_held,
        }


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
        if r["signal"] == "HOLD":
            continue
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


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _daily_counts(start: datetime, end: datetime) -> dict:
    with SessionLocal() as db:
        buy_signals = db.query(SignalLog).filter(
            SignalLog.timestamp >= start,
            SignalLog.timestamp < end,
            SignalLog.signal == "BUY",
        ).count()
        sell_signals = db.query(SignalLog).filter(
            SignalLog.timestamp >= start,
            SignalLog.timestamp < end,
            SignalLog.signal == "SELL",
        ).count()
        telegram_sent = db.query(SignalLog).filter(
            SignalLog.timestamp >= start,
            SignalLog.timestamp < end,
            SignalLog.telegram_sent == 1,
        ).count()
        outcome_rows = db.query(SignalOutcome).filter(
            SignalOutcome.entry_timestamp >= start,
            SignalOutcome.entry_timestamp < end,
        ).all()

    total_signals = buy_signals + sell_signals
    return _build_performance_dict(
        start.date().isoformat(),
        total_signals=total_signals,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        telegram_sent=telegram_sent,
        outcomes=outcome_rows,
    )


def performance_daily(target_date: Optional[date] = None) -> dict:
    target = target_date or datetime.now(timezone.utc).date()
    start, end = _day_bounds(target)
    return _daily_counts(start, end)


def performance_summary(start_date: date, end_date: date) -> dict:
    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)

    with SessionLocal() as db:
        signal_rows = db.query(SignalLog).filter(
            SignalLog.timestamp >= start,
            SignalLog.timestamp < end,
        ).all()
        outcome_rows = db.query(SignalOutcome).filter(
            SignalOutcome.entry_timestamp >= start,
            SignalOutcome.entry_timestamp < end,
        ).all()

    total_signals = len(signal_rows)
    buy_signals = sum(1 for row in signal_rows if row.signal == "BUY")
    sell_signals = sum(1 for row in signal_rows if row.signal == "SELL")
    total_signals = buy_signals + sell_signals
    telegram_sent = sum(1 for row in signal_rows if row.telegram_sent == 1)
    metrics = _build_performance_dict(
        start_date.isoformat(),
        total_signals=total_signals,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        telegram_sent=telegram_sent,
        outcomes=outcome_rows,
    )

    pair_rows = _performance_group_rows(outcome_rows, key="pair")
    timeframe_rows = _performance_group_rows(outcome_rows, key="timeframe")
    metrics["range"] = {"from": start_date.isoformat(), "to": end_date.isoformat()}
    metrics["best_pair"] = _best_key(pair_rows)
    metrics["worst_pair"] = _worst_key(pair_rows)
    metrics["best_timeframe"] = _best_key(timeframe_rows)
    metrics["worst_timeframe"] = _worst_key(timeframe_rows)
    return metrics


def performance_by_pair(start_date: date, end_date: date) -> list[dict]:
    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)
    with SessionLocal() as db:
        rows = db.query(SignalOutcome).filter(
            SignalOutcome.entry_timestamp >= start,
            SignalOutcome.entry_timestamp < end,
        ).all()
    return _performance_group_rows(rows, key="pair")


def performance_by_timeframe(start_date: date, end_date: date) -> list[dict]:
    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)
    with SessionLocal() as db:
        rows = db.query(SignalOutcome).filter(
            SignalOutcome.entry_timestamp >= start,
            SignalOutcome.entry_timestamp < end,
        ).all()
    return _performance_group_rows(rows, key="timeframe")


def _build_performance_dict(
    period_label: str,
    *,
    total_signals: int,
    buy_signals: int,
    sell_signals: int,
    telegram_sent: int,
    outcomes: list[SignalOutcome],
) -> dict:
    resolved = [row for row in outcomes if row.status == "resolved"]
    wins = sum(1 for row in resolved if row.outcome == "win")
    losses = sum(1 for row in resolved if row.outcome == "loss")
    expired = sum(1 for row in resolved if row.outcome == "expired")
    neutral = sum(1 for row in resolved if row.outcome == "neutral")
    open_signals = sum(1 for row in outcomes if row.status == "open")
    resolved_non_expired = [row for row in resolved if row.outcome in {"win", "loss", "neutral"}]
    denominator = wins + losses
    avg_return = None
    if resolved_non_expired:
        avg_return = round(
            sum((row.return_pct or 0.0) for row in resolved_non_expired) / len(resolved_non_expired),
            4,
        )

    return {
        "date": period_label,
        "total_signals": total_signals,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_signals": 0,
        "telegram_sent": telegram_sent,
        "resolved_signals": len(resolved),
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "neutral": neutral,
        "open_signals": open_signals,
        "win_rate": round((wins / denominator) * 100, 2) if denominator else None,
        "avg_return_pct": avg_return,
    }


def _performance_group_rows(rows: list[SignalOutcome], key: str) -> list[dict]:
    grouped: dict[str, list[SignalOutcome]] = {}
    for row in rows:
        grouped.setdefault(getattr(row, key), []).append(row)

    items: list[dict] = []
    for label, group_rows in grouped.items():
        resolved = [row for row in group_rows if row.status == "resolved"]
        wins = sum(1 for row in resolved if row.outcome == "win")
        losses = sum(1 for row in resolved if row.outcome == "loss")
        denominator = wins + losses
        resolved_with_return = [row for row in resolved if row.return_pct is not None]
        items.append({
            key: label,
            "total_signals": len(group_rows),
            "resolved_signals": len(resolved),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / denominator) * 100, 2) if denominator else None,
            "avg_return_pct": round(
                sum((row.return_pct or 0.0) for row in resolved_with_return) / len(resolved_with_return),
                4,
            ) if resolved_with_return else None,
        })

    return sorted(items, key=lambda item: (item["win_rate"] is None, -(item["win_rate"] or 0), item[key]))


def _best_key(items: list[dict]) -> Optional[str]:
    ranked = [item for item in items if item.get("win_rate") is not None]
    if not ranked:
        return None
    first = ranked[0]
    return first.get("pair") or first.get("timeframe")


def _worst_key(items: list[dict]) -> Optional[str]:
    ranked = [item for item in items if item.get("win_rate") is not None]
    if not ranked:
        return None
    last = sorted(ranked, key=lambda item: ((item["win_rate"] or 0), item.get("pair") or item.get("timeframe")))[0]
    return last.get("pair") or last.get("timeframe")


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
