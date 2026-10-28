# UK wind day-ahead forecast accuracy

Shows the latest national wind forecast (Elexon BMRS `WINDFOR`) a buyer had at the day-ahead decision
point, against actual wind generation (`FUELHH`, fuelType `WIND`). It also measures how wrong those
forecasts were across January 2026.

**Live app:** _TODO: Vercel URL_

## AI tools disclosure

AI tools were used to build this project. Claude Code (Anthropic) helped with scaffolding, code,
tests and documentation. I reviewed, ran and verified all output, and I own the design decisions
and the analysis.

## Key definitions

- **Latest forecast available**: for each delivery day D (UK local), take the `WINDFOR` run with the
  greatest `publishTime` at or before **D-1 09:00 UK**. That is just before the 09:20 GB day-ahead
  auction gate. You can change the cutoff with the `cutoff` query parameter or in the UI.
- **Error** = forecast − actual (MW). A positive error is an over-forecast, i.e. a shortfall the
  buyer must cover with extra (thermal) power.
- **P90 shortfall**: the 90th percentile of error. Buying this many MW of extra power would have
  covered the shortfall in 90% of hours.
- `WINDFOR` is hourly and `FUELHH` is half-hourly, so they are compared at hourly `startTime`s.

## Finding: the forecast runs high, more so when it is windy

Day-ahead forecasts over-forecast delivered wind by about 1.9 GW on average. Forecasts made under 2
hours ahead are also about 1.6 GW high, and the gap grows with wind level (+0.6 GW below 5 GW of
forecast wind, +4.5 GW above 20 GW). That fits curtailment, where wind farms are paid to turn down
when the grid can't take their output, so metered `FUELHH` output falls below the unconstrained
`WINDFOR` forecast. It is a hypothesis: confirming it needs balancing-action data, which is outside
this brief's Elexon wind-only scope.

## Layout

| Path | What |
|---|---|
| `backend/fetch_data.py` | One-off pull of the January 2026 window from BMRS into `data/*.csv` |
| `backend/analysis.py` | Day-ahead forecast selection + MAE/RMSE/bias/MAPE/P90, by day, hour, lead time and forecast level, plus an error histogram |
| `backend/app.py` | FastAPI: `GET /api/day?date=&cutoff=`, `GET /api/accuracy?cutoff=`; also serves the built UI |
| `backend/test_analysis.py` | pytest |
| `api/index.py` | Vercel Python entrypoint |
| `frontend/` | Next.js (App Router, static export) + Recharts UI; claymorphism surfaces on an Apple system palette |
| `data/` | Committed BMRS snapshot (the data is historical, so it is not fetched live) |

## Run

```bash
# Docker (API + UI on :8000)
docker build -t wind . && docker run -p 8000:8000 wind

# Local dev
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn backend.app:app --reload        # API on :8000
cd frontend && npm install && npm run dev          # UI on :3000, proxies /api to :8000

# Tests / refresh data
.venv/bin/python -m pytest -q backend
.venv/bin/python -m backend.fetch_data
```

## Deploy

`vercel deploy`. `vercel.json` builds the Next.js UI as a static export (`frontend/out`) and runs `api/index.py` as a Python
function. The Dockerfile is for local and container hosting (it runs on Heroku's container stack as-is).
