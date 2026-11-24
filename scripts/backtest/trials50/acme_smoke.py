#!/usr/bin/env python3
"""Acme smoke on the scratch backend (BACKTEST_BASE, default :8024).

Replicates verify-local.sh steps 4 + 8 exactly: create the Acme run
(cash triangular(60,100,140), pipeline normal(1.0,0.1), cac
triangular(8000,12000,20000), seed 7, tick_count 2) then Monte Carlo
(trials 5, seed 42, metric cash, loss_threshold 90.0). The P50 must be
exactly 99.8143 (e047f50 baseline).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error

import backtest_common  # repo root on sys.path, shared config

BASE = backtest_common.get_base()
SECRET = backtest_common.get_secret()


def call(method: str, path: str, payload: dict | None = None):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-mingjian-local-proxy", SECRET)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body


def main() -> None:
    st, body = call("POST", "/simulation/runs", {
        "company_id": "docker-verify-co",
        "company_name": "Docker Verify Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
        "variable_set": {
            "name": "case",
            "variables": [
                {"id": "cash", "unit": "k",
                 "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
                 "evidence_ref": "estimate: founder judgment"},
                {"id": "pipeline", "unit": "x",
                 "distribution": {"type": "normal", "mean": 1.0, "std": 0.1},
                 "evidence_ref": "estimate: founder judgment"},
                {"id": "cac", "unit": "yuan",
                 "distribution": {"type": "triangular", "min": 8000, "mode": 12000, "max": 20000},
                 "evidence_ref": "estimate:q3-report"},
            ],
            "internal": {"team": "20 people"},
        },
    })
    print(f"create run -> {st}")
    if st != 201 or "id" not in body:
        print(json.dumps(body)[:500])
        sys.exit(1)
    run_id = body["id"]
    print(f"run_id={run_id}")
    st, body = call("POST", f"/runs/{run_id}/monte-carlo",
                    {"trials": 5, "seed": 42, "metric": "cash",
                     "loss_threshold": 90.0})
    print(f"monte-carlo -> {st}")
    if st != 201:
        print(json.dumps(body)[:500])
        sys.exit(1)
    b = body["baseline"]
    print(f"P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']}")
    print("ACME_P50_EXACT_99.8143:", b["p50"] == 99.8143)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "acme-smoke-c1.json"), "w") as f:
        json.dump({"run_id": run_id, "baseline": b}, f, indent=2)
    sys.exit(0 if b["p50"] == 99.8143 else 1)


if __name__ == "__main__":
    main()
