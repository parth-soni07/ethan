from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from backend import analysis

app = FastAPI(title="UK wind day-ahead forecast accuracy")
CUTOFF = Query("09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="D-1 gate time, UK local")


@app.get("/api/day")
def day(date: str = Query(..., pattern=r"^2026-01-\d{2}$"), cutoff: str = CUTOFF):
    return analysis.day(date, cutoff)


@app.get("/api/accuracy")
def accuracy(cutoff: str = CUTOFF):
    return analysis.accuracy(cutoff)


# Docker image serves the built UI too; on Vercel the static build is served by the CDN.
dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
