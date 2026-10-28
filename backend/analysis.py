"""Day-ahead forecast selection and accuracy metrics. Pure functions over DataFrames."""
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
UK = "Europe/London"
LEAD_BUCKETS = [0, 6, 12, 24, 36, 48, 72]
LEVEL_BANDS = [0, 5000, 10000, 15000, 20000, 30000]


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
    da["level"] = pd.cut(da["forecast"], LEVEL_BANDS, right=False)
    allf = join(forecasts, actuals)
    allf["lead_h"] = (allf["startTime"] - allf["publishTime"]).dt.total_seconds() / 3600
    allf = allf[allf["lead_h"] >= 0]
    allf["lead"] = pd.cut(allf["lead_h"], LEAD_BUCKETS, right=False)
    counts, edges = np.histogram(da["error"].clip(-8000, 11999), bins=range(-8000, 12001, 1000))
    return {
        "cutoff": cutoff,
        "overall": metrics(da),
        "by_day": [{"day": d, **metrics(g)} for d, g in da.groupby("day")],
        "by_hour": [{"hour": h, **metrics(g)} for h, g in da.groupby("hour")],
        "by_lead": [{"lead": f"{iv.left}-{iv.right}h", **metrics(g)}
                    for iv, g in allf.groupby("lead", observed=True)],
        # Over-forecast grows with wind level: the signature of curtailment (metered output is
        # constrained off when the grid can't take it), so bias is not a constant offset.
        "by_level": [{"level": f"{iv.left // 1000}-{iv.right // 1000} GW", **metrics(g)}
                     for iv, g in da.groupby("level", observed=True)],
        "histogram": [{"from": int(lo), "to": int(lo + 1000), "count": int(c)}
                      for lo, c in zip(edges[:-1], counts)],
    }


def day(date: str, cutoff: str = "09:00") -> list[dict]:
    actuals, forecasts = load()
    start = pd.Timestamp(date, tz=UK)
    window = lambda s: (s >= start) & (s < start + pd.Timedelta(days=1))
    da = day_ahead(forecasts, cutoff)
    out = (actuals[window(actuals["startTime"].dt.tz_convert(UK))]
           .merge(da[window(da["startTime"].dt.tz_convert(UK))], on="startTime", how="left",
                  suffixes=("_act", "_fc")))
    return [{"startTime": r.startTime.isoformat(),
             "actual": r.generation_act,
             "forecast": None if pd.isna(r.generation_fc) else r.generation_fc,
             "publishTime": None if pd.isna(r.publishTime) else r.publishTime.isoformat()}
            for r in out.itertuples()]
