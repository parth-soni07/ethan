import os
from datetime import date as Date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from backend import analysis

analysis.load()  # fail at boot, not on the first request, if the data snapshot is missing or bad

app = FastAPI(title="UK wind day-ahead forecast accuracy")
CUTOFF = Query(analysis.DEFAULT_CUTOFF, pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
               description="Decision time on the day before delivery, UK local (HH:MM)")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


# The UI (old-champagne) is a separate deploy. Cross-origin reads are allowed only for origins listed
# in ALLOWED_ORIGINS (comma-separated); unset means same-origin only.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if ALLOWED_ORIGINS:
        # The CORS middleware only varies on Origin when the request carries one; without this, an
        # edge cache can serve a no-Origin copy (no CORS header) to the browser and the fetch fails.
        response.headers.add_vary_header("Origin")
    return response


@app.get("/api/day")
def day(date: Date, cutoff: str = CUTOFF):
    first, last = analysis.date_range()
    if not first <= date.isoformat() <= last:
        raise HTTPException(422, f"date must be between {first} and {last}")
    return analysis.day(date.isoformat(), cutoff)


@app.get("/api/accuracy")
def accuracy(cutoff: str = CUTOFF):
    return analysis.accuracy(cutoff)


# Unknown /api paths get a JSON 404 here rather than the UI's HTML 404 from the static mount.
@app.api_route("/api/{rest:path}", methods=["GET", "HEAD"], include_in_schema=False)
def api_not_found(rest: str):
    raise HTTPException(404, "Not Found")

