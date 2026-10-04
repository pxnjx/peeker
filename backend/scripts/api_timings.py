"""Latency probe for the running API: median/max per endpoint, plus payload size.

Run against a live backend:  .venv/Scripts/python.exe scripts/api_timings.py [base-url]

The data routes need a dashboard session cookie, so the script signs in through the
frontend's real /api/login first. The password comes from PEEKER_DASHBOARD_PASSWORD,
falling back to DASHBOARD_PASSWORD in frontend/.env.local; the login host comes from
PEEKER_LOGIN_BASE (default http://localhost:3001).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
REPEAT = int(sys.argv[2]) if len(sys.argv) > 2 else 5

PATHS = [
    "/health",
    "/api/stats",
    "/api/businesses",
    "/api/alerts",
    "/api/reviews?limit=300",
    "/api/reviews?limit=2000",
]


def session_cookie() -> str:
    """Sign in and return 'peeker_session=<token>'; /health needs no session."""
    password = os.environ.get("PEEKER_DASHBOARD_PASSWORD")
    if not password:
        env = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend" / ".env.local"
        match = re.search(r"^DASHBOARD_PASSWORD=(.*)$", env.read_text(), re.M)
        if not match:
            raise SystemExit("set PEEKER_DASHBOARD_PASSWORD or keep DASHBOARD_PASSWORD in frontend/.env.local")
        password = match.group(1).strip()
    base = os.environ.get("PEEKER_LOGIN_BASE", "http://localhost:3001")
    request = urllib.request.Request(
        f"{base}/api/login",
        data=json.dumps({"password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.headers.get("Set-Cookie", "")
    token = re.search(r"peeker_session=([^;]+)", raw)
    if not token:
        raise SystemExit(f"login did not set a session cookie: {raw!r}")
    return f"peeker_session={token.group(1)}"


COOKIE = session_cookie()


def probe(path: str) -> tuple[str, list[float], int]:
    samples: list[float] = []
    size = 0
    request = urllib.request.Request(BASE + path)
    if path != "/health":
        request.add_header("Cookie", COOKIE)
    for _ in range(REPEAT):
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
        samples.append((time.perf_counter() - started) * 1000)
        size = len(body)
    return path, samples, size


print(f"base={BASE} repeat={REPEAT}\n")
print(f"{'endpoint':32s} {'min':>8s} {'med':>8s} {'max':>8s} {'bytes':>10s}  rows")
for path in PATHS:
    try:
        _, samples, size = probe(path)
        payload_request = urllib.request.Request(BASE + path)
        if path != "/health":
            payload_request.add_header("Cookie", COOKIE)
        payload_probe = urllib.request.urlopen(payload_request, timeout=60)
        payload = json.loads(payload_probe.read())
        rows = len(payload) if isinstance(payload, list) else "-"
    except Exception as exc:  # noqa: BLE001
        print(f"{path:32s} ERROR {exc}")
        continue
    print(
        f"{path:32s} {min(samples):8.1f} {statistics.median(samples):8.1f} {max(samples):8.1f} "
        f"{size:10d}  {rows}"
    )
