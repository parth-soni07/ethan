"""Day-ahead forecast selection and accuracy metrics. Pure functions over DataFrames."""
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
UK = "Europe/London"
LEAD_BUCKETS = [0, 6, 12, 24, 36, 48, 72]
LEVEL_BANDS = [0, 5000, 10000, 15000, 20000, np.inf]
LEVEL_LABELS = ["0-5 GW", "5-10 GW", "10-15 GW", "15-20 GW", "20+ GW"]
BIN = 1000  # histogram bin width, MW


@cache
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    actuals = pd.read_csv(DATA / "actuals.csv", parse_dates=["startTime"])
    forecasts = pd.read_csv(DATA / "forecasts.csv", parse_dates=["publishTime", "startTime"])
    return actuals, forecasts


def day_ahead(forecasts: pd.DataFrame, cutoff: str = "09:00") -> pd.DataFrame:
    """Per startTime, the latest forecast published at or before D-1 `cutoff` (UK local time),
    where D is the UK delivery day of that startTime."""
    local = forecasts["startTime"].dt.tz_convert(UK)
    gate = (local.dt.normalize() - pd.Timedelta(days=1) + pd.Timedelta(cutoff + ":00"))
    eligible = forecasts[forecasts["publishTime"] <= gate.dt.tz_convert("UTC")]
    return eligible.loc[eligible.groupby("startTime")["publishTime"].idxmax()].reset_index(drop=True)


def join(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    # WINDFOR is hourly, FUELHH half-hourly: compare on the forecast's hourly startTime.
    df = forecasts.merge(actuals, on="startTime", suffixes=("_fc", "_act"))
    df = df.rename(columns={"generation_fc": "forecast", "generation_act": "actual"})
    df["error"] = df["forecast"] - df["actual"]  # > 0: over-forecast -> shortfall to buy
    return df


def metrics(df: pd.DataFrame) -> dict:
    e = df["error"]
    return {
        "n": int(len(df)),
        "mae": float(e.abs().mean()),
        "rmse": float(np.sqrt((e ** 2).mean())),
        "bias": float(e.mean()),
        "mape": float((e.abs() / df["actual"]).mean() * 100),
        "p10": float(e.quantile(0.1)),
        "p50": float(e.quantile(0.5)),
        # MW of extra procurement that would have covered the shortfall in 90% of hours.
        "p90_shortfall": float(max(e.quantile(0.9), 0)),
    }


@cache  # data is static; warm serverless instances reuse results per cutoff
def accuracy(cutoff: str = "09:00") -> dict:
    actuals, forecasts = load()
    da = join(day_ahead(forecasts, cutoff), actuals)
    local = da["startTime"].dt.tz_convert(UK)
    da["hour"], da["day"] = local.dt.hour, local.dt.strftime("%Y-%m-%d")
    da["level"] = pd.cut(da["forecast"], LEVEL_BANDS, labels=LEVEL_LABELS, right=False)
    allf = join(forecasts, actuals)
    allf["lead_h"] = (allf["startTime"] - allf["publishTime"]).dt.total_seconds() / 3600
    allf = allf[allf["lead_h"] >= 0]
    allf["lead"] = pd.cut(allf["lead_h"], LEAD_BUCKETS, right=False)
    lo, hi = np.floor(da["error"].min() / BIN) * BIN, np.ceil(da["error"].max() / BIN) * BIN
    counts, edges = np.histogram(da["error"], bins=np.arange(lo, max(hi, lo + BIN) + 1, BIN))
    return {
        "cutoff": cutoff,
        "overall": metrics(da),
        "by_day": [{"day": d, **metrics(g)} for d, g in da.groupby("day")],
        "by_hour": [{"hour": h, **metrics(g)} for h, g in da.groupby("hour")],
        "by_lead": [{"lead": f"{iv.left}-{iv.right}h", **metrics(g)}
                    for iv, g in allf.groupby("lead", observed=True)],
        # Over-forecast grows with wind level: the signature of curtailment (metered output is
        # constrained off when the grid can't take it), so bias is not a constant offset.
        "by_level": [{"level": lvl, **metrics(g)}
                     for lvl, g in da.groupby("level", observed=True)],
        "histogram": [{"from": int(a), "to": int(b), "count": int(c)}
                      for a, b, c in zip(edges[:-1], edges[1:], counts)],
    }


def day(date: str, cutoff: str = "09:00") -> dict:
    actuals, forecasts = load()
    start = pd.Timestamp(date, tz=UK)
    window = lambda df: df[(df["startTime"] >= start) & (df["startTime"] < start + pd.Timedelta(days=1))]
    da, act = window(day_ahead(forecasts, cutoff)), window(actuals)
    joined = join(da, act)
    out = act.merge(da, on="startTime", how="left", suffixes=("_act", "_fc"))
    return {
        "date": date,
        "metrics": metrics(joined) if len(joined) else None,
        "points": [{"startTime": r.startTime.isoformat(),
                    "actual": r.generation_act,
                    "forecast": None if pd.isna(r.generation_fc) else r.generation_fc,
                    "publishTime": None if pd.isna(r.publishTime) else r.publishTime.isoformat()}
                   for r in out.itertuples()],
    }
