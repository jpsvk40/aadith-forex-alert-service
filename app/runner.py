"""
runner.py — one full poll cycle.
Called by scheduler.py on each tick.
Independently testable: runner.run_cycle() can be called manually.

Flow per pair+timeframe:
  fetch candles → compute indicators → evaluate strategy
  → if BUY/SELL and not suppressed → send Telegram → log with sent=True
  → if HOLD or suppressed → log with sent=False (HOLD skips Telegram always)
"""

import logging
from datetime import timezone

from app.config import settings
from app.data_provider import fetch_candles
from app.indicators import compute_indicators
from app.strategy import evaluate
from app.signal_repository import (
    should_suppress,
    log_signal,
    create_signal_outcome,
    open_outcomes,
    resolve_signal_outcome,
)
from app.alert_dispatcher import send_alert

logger = logging.getLogger(__name__)


def run_cycle():
    """Execute one poll cycle across all configured pairs and timeframes."""
    for pair in settings.pairs:
        for timeframe in settings.timeframes:
            _process(pair, timeframe)
    _resolve_open_outcomes()


def _process(pair: str, timeframe: str):
    try:
        df = fetch_candles(pair, timeframe)
        df = compute_indicators(df)
        result = evaluate(df)

        if result.signal == "HOLD":
            # Log HOLD for audit trail but never send Telegram
            log_signal(pair, timeframe, result, telegram_sent=False)
            logger.debug("HOLD %s %s — skipping alert", pair, timeframe)
            return

        if should_suppress(pair, timeframe, result):
            logger.debug(
                "Suppressed duplicate %s %s %s (strategy_v%d)",
                result.signal, pair, timeframe, result.strategy_version,
            )
            return

        sent = send_alert(pair, timeframe, result)
        row = log_signal(pair, timeframe, result, telegram_sent=sent)
        create_signal_outcome(row, evaluation_bars=_evaluation_bars(timeframe))

    except Exception as exc:
        logger.error("runner._process failed [%s %s]: %s", pair, timeframe, exc, exc_info=True)


def _resolve_open_outcomes():
    for outcome in open_outcomes():
        try:
            bars = _evaluation_bars(outcome.timeframe)
            df = fetch_candles(outcome.pair, outcome.timeframe)
            entry_timestamp = outcome.entry_timestamp
            if entry_timestamp.tzinfo is None:
                entry_timestamp = entry_timestamp.replace(tzinfo=timezone.utc)
            else:
                entry_timestamp = entry_timestamp.astimezone(timezone.utc)
            future = df[df.index > entry_timestamp]
            if len(future) < bars:
                continue

            exit_candle = future.iloc[bars - 1]
            exit_timestamp = future.index[bars - 1].to_pydatetime()
            if exit_timestamp.tzinfo is None:
                exit_timestamp = exit_timestamp.replace(tzinfo=timezone.utc)
            resolve_signal_outcome(
                outcome.id,
                exit_price=float(exit_candle["close"]),
                exit_timestamp=exit_timestamp,
                bars_held=bars,
            )
        except Exception as exc:
            logger.error(
                "runner._resolve_open_outcomes failed [%s %s #%s]: %s",
                outcome.pair,
                outcome.timeframe,
                outcome.id,
                exc,
                exc_info=True,
            )


def _evaluation_bars(timeframe: str) -> int:
    timeframe_overrides = {
        "1min": 5,
        "5min": 3,
    }
    return timeframe_overrides.get(timeframe, settings.evaluation_bars_default)
