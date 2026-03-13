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

from app.config import settings
from app.data_provider import fetch_candles
from app.indicators import compute_indicators
from app.strategy import evaluate
from app.signal_repository import should_suppress, log_signal
from app.alert_dispatcher import send_alert

logger = logging.getLogger(__name__)


def run_cycle():
    """Execute one poll cycle across all configured pairs and timeframes."""
    for pair in settings.pairs:
        for timeframe in settings.timeframes:
            _process(pair, timeframe)


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
        log_signal(pair, timeframe, result, telegram_sent=sent)

    except Exception as exc:
        logger.error("runner._process failed [%s %s]: %s", pair, timeframe, exc, exc_info=True)
