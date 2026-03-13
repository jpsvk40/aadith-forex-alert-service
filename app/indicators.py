"""
Technical indicator calculations.
All functions take a DataFrame (close prices required) and return Series.
"""

import pandas as pd
import ta


def ema(series: pd.Series, period: int) -> pd.Series:
    return ta.trend.EMAIndicator(close=series, window=period).ema_indicator()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(close=series, window=period).rsi()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds ema9, ema21, rsi14 columns to the DataFrame.
    Returns the same DataFrame with new columns appended.
    """
    df = df.copy()
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["rsi14"] = rsi(df["close"], 14)
    return df
