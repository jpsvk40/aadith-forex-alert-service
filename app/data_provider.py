"""
Fetches OHLCV candle data from Twelve Data API.
Returns a pandas DataFrame with enough history for indicator calculation.
Minimum candles required: 30 (covers EMA21 + RSI14 warmup).
"""

import logging
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from twelvedata import TDClient

from app.config import settings

logger = logging.getLogger(__name__)

MIN_CANDLES = 30  # EMA21 needs 21, RSI14 needs 14 — 30 gives safe warmup

_client: Optional[TDClient] = None


def _get_client() -> TDClient:
    global _client
    if _client is None:
        _client = TDClient(apikey=settings.twelvedata_api_key)
    return _client


def fetch_candles(pair: str, timeframe: str, outputsize: int = MIN_CANDLES) -> pd.DataFrame:
    """
    Fetch OHLCV candles for a forex pair.
    Returns DataFrame with columns: [open, high, low, close, volume] indexed by datetime.
    Raises on API error or empty response.
    """
    try:
        client = _get_client()
        ts = client.time_series(
            symbol=pair,
            interval=timeframe,
            outputsize=outputsize,
            timezone="UTC",
        )
        df = ts.as_pandas()

        if df is None or df.empty:
            raise ValueError(f"Empty response for {pair} {timeframe}")

        df = df.sort_index()  # oldest first
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.rename(columns=str.lower)

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.debug("Fetched %d candles for %s %s", len(df), pair, timeframe)
        return df

    except Exception as exc:
        logger.error("data_provider.fetch_candles failed [%s %s]: %s", pair, timeframe, exc)
        raise


def check_provider_health() -> dict:
    """
    Quick connectivity check — fetches 1 candle for the first configured pair.
    Returns status dict consumed by GET /providers/status.
    """
    pair = settings.pairs[0]
    timeframe = settings.timeframes[0]
    try:
        df = fetch_candles(pair, timeframe, outputsize=1)
        last_ts = df.index[-1].isoformat() if not df.empty else None
        return {
            "status": "ok",
            "provider": "twelvedata",
            "last_fetch_utc": last_ts,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider": "twelvedata",
            "last_fetch_utc": None,
            "error": str(exc),
        }
