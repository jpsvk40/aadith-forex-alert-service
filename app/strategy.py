"""
Signal generation strategy.
BUY  : EMA9 crosses above EMA21 AND RSI > 55
SELL : EMA9 crosses below EMA21 AND RSI < 45
HOLD : no qualifying crossover

Crossover is detected by comparing current vs previous candle values —
NOT just current state — so the signal fires once on the candle of the cross,
not on every subsequent candle while EMA9 stays above EMA21.

STRATEGY_VERSION is baked into every signal. Incrementing it resets
dedup suppression intentionally (new logic = new signal window).
"""

from dataclasses import dataclass
from typing import Literal
import pandas as pd

from app.config import settings

Signal = Literal["BUY", "SELL", "HOLD"]

RSI_BUY_THRESHOLD = 55
RSI_SELL_THRESHOLD = 45


@dataclass
class SignalResult:
    signal: Signal
    entry_price: float
    rsi: float
    ema9: float
    ema21: float
    strategy_version: int


def evaluate(df: pd.DataFrame) -> SignalResult:
    """
    Evaluate the last two candles of an indicator-enriched DataFrame.
    Requires columns: close, ema9, ema21, rsi14.
    Raises ValueError if insufficient data.
    """
    required = {"close", "ema9", "ema21", "rsi14"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame missing columns: {required - set(df.columns)}")

    clean = df.dropna(subset=["ema9", "ema21", "rsi14"])
    if len(clean) < 2:
        raise ValueError("Need at least 2 valid indicator rows to detect crossover")

    prev = clean.iloc[-2]
    curr = clean.iloc[-1]

    curr_rsi = float(curr["rsi14"])
    curr_ema9 = float(curr["ema9"])
    curr_ema21 = float(curr["ema21"])
    entry_price = float(curr["close"])

    # Crossover: previous candle had the opposite relationship
    ema_crossed_up = float(prev["ema9"]) <= float(prev["ema21"]) and curr_ema9 > curr_ema21
    ema_crossed_down = float(prev["ema9"]) >= float(prev["ema21"]) and curr_ema9 < curr_ema21

    if ema_crossed_up and curr_rsi > RSI_BUY_THRESHOLD:
        signal: Signal = "BUY"
    elif ema_crossed_down and curr_rsi < RSI_SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"

    return SignalResult(
        signal=signal,
        entry_price=entry_price,
        rsi=curr_rsi,
        ema9=curr_ema9,
        ema21=curr_ema21,
        strategy_version=settings.strategy_version,
    )
