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
        f"{emoji} *{signal_result.signal}* - {pair} ({timeframe})\n"
        f"Entry: `{signal_result.entry_price:.5f}`"
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
    return _send_payload(payload, context=f"{signal_result.signal} {pair} {timeframe}")


def send_text_message(text: str) -> bool:
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    return _send_payload(payload, context="daily report")


def send_outcome_alert(
    pair: str,
    timeframe: str,
    signal: str,
    entry_price: float,
    exit_price: float,
    outcome: str,
    return_pct: float,
    bars_held: int,
) -> bool:
    emoji = "✅" if outcome == "win" else "❌" if outcome == "loss" else "⚪"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": (
            f"{emoji} *{outcome.upper()}* - {pair} ({timeframe})\n"
            f"Signal: `{signal}`\n"
            f"Entry: `{entry_price:.5f}`\n"
            f"Exit: `{exit_price:.5f}`\n"
            f"Return: `{return_pct:.3f}%`\n"
            f"Bars held: `{bars_held}`"
        ),
        "parse_mode": "Markdown",
    }
    return _send_payload(payload, context=f"outcome {outcome} {pair} {timeframe}")


def _send_payload(payload: dict, context: str) -> bool:
    url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram message sent: %s", context)
        return True
    except Exception as exc:
        logger.error("Telegram send failed [%s]: %s", context, exc)
        return False
