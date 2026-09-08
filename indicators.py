import pandas as pd


def compute_rsi(closes, period=14):
    """
    Standard Wilder RSI calculation.
    `closes` should be a pandas Series of closing prices, sorted oldest to newest.
    Returns a Series of RSI values (0-100), same length as input, with the
    first `period` entries as NaN (not enough history yet to compute).
    """
    delta = closes.diff()  # day-over-day price change

    gains = delta.clip(lower=0)   # keep only positive changes, zero out losses
    losses = -delta.clip(upper=0)  # keep only negative changes (as positive numbers), zero out gains

    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Special case: if there were zero losses in the window, RSI is defined as 100
    rsi = rsi.where(avg_loss != 0, 100)

    return rsi

import numpy as np


def compute_std_dev(closes, window=252):
    """
    Annualized standard deviation of daily returns (volatility).
    `closes` should be a pandas Series of closing prices, sorted oldest to newest.
    `window=252` approximates 1 trading year -- uses less if not enough history.
    """
    daily_returns = closes.pct_change().dropna()

    if len(daily_returns) < 2:
        return None

    window = min(window, len(daily_returns))
    recent_returns = daily_returns.tail(window)

    daily_std = recent_returns.std()
    annualized_std = daily_std * np.sqrt(252)  # scales daily volatility up to a yearly figure

    return annualized_std