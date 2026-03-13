"""
Telegram alert dispatcher.
Dumb transport layer — receives a formatted message, sends it.
No signal logic, no dedup, no DB access here.
"""

import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _build_message(pair: str, timeframe: str, signal_result) -> str:
    emoji = "🟢" if signal_result.signal == "BUY" else "🔴"
    return (
        f"{emoji} *{signal_result.signal}* — {pair} ({timeframe})\n"
        f"Price: `{signal_result.entry_price:.5f}`\n"
        f"RSI: `{signal_result.rsi:.1f}`\n"
        f"EMA9: `{signal_result.ema9:.5f}`\n"
        f"EMA21: `{signal_result.ema21:.5f}`\n"
        f"Strategy v{signal_result.strategy_version}"
    )


def send_alert(pair: str, timeframe: str, signal_result) -> bool:
    """
    Send a Telegram message for a BUY/SELL signal.
    Returns True on success, False on failure (logged, never raises).
    """
    if signal_result.signal == "HOLD":
        return False  # caller should not pass HOLD, but guard anyway

    url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": _build_message(pair, timeframe, signal_result),
        "parse_mode": "Markdown",
    }
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram alert sent: %s %s %s", signal_result.signal, pair, timeframe)
        return True
    except Exception as exc:
        logger.error("Telegram send failed [%s %s]: %s", pair, timeframe, exc)
        return False
