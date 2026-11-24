#!/usr/bin/env python3
"""Step 1 profit-MC pass (post-derive, derive-safe).

Runs AFTER the four OFF/ON run scripts have finished (and after derive),
so the profit ensembles can never overwrite the stored ensemble derive
reads. For every case (desay-2015, desay-2020, huawei, nokia) x OFF/ON:
anchor + every child arm gets one profit Monte Carlo (trials 50,
seed 42, metric profit). The loss_threshold is that run's own tick-0
profit from its saved replay package — the same "initial value"
convention the revenue MCs use (revenue_loss_threshold).

Writes 03c-anchor-monte-carlo-profit.json and
06c-mc-profit-<tag>.json next to the run's other raw files, plus a
profit summary to profit-summary.json. Failures are recorded per arm
and never abort the pass (a missing profit field on some domain would
be a finding, not a crash).

Usage: python3 run_profit_mc.py   (scratch backend must be up — see start-backend.sh)
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

import backtest_common  # repo root on sys.path, shared config

BASE = backtest_common.get_base()
HERE = str(backtest_common.get_run_dir())
SECRET = backtest_common.get_secret()


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | str]:
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


def save(case_dir: str, step: str, status: int, obj) -> None:
    with open(os.path.join(case_dir, f"{step}.json"), "w") as f:
        json.dump({"http_status": status, "body": obj}, f, indent=2, ensure_ascii=False)


def tag_of(arm_name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in arm_name.replace(" ", "_"))


def tick0_profit(replay_path: str) -> float | None:
    """Tick-0 profit from a saved replay-package JSON, else None."""
    if not os.path.exists(replay_path):
        return None
    body = json.load(open(replay_path))["body"]
    pkg = body.get("package")
    if isinstance(pkg, str):
        pkg = json.loads(pkg)
    for snap in pkg.get("snapshots", []):
        if snap.get("tick") == 0:
            value = (snap.get("state") or {}).get("profit")
            return float(value) if value is not None else None
    return None


def run_profit_mc(case_dir: str, run_id: str, step: str, replay_file: str) -> dict:
    replay_path = os.path.join(case_dir, replay_file)
    threshold = tick0_profit(replay_path)
    if threshold is None:
        return {"error": f"no tick-0 profit in {os.path.basename(replay_path)}"}
    st, body = call("POST", f"/runs/{run_id}/monte-carlo",
                    {"trials": 50, "seed": 42, "metric": "profit",
                     "loss_threshold": threshold})
    save(case_dir, step, st, body)
    if st != 201:
        return {"error": f"profit mc failed http={st}", "body": str(body)[:300]}
    b = body["baseline"]
    print(f"  {step}: profit P50={b['p50']} P10={b['p10']} "
          f"p_loss={b['p_loss']} decline_p={b.get('decline_probability')}", flush=True)
    return {"p50": b["p50"], "p10": b["p10"], "p_loss": b["p_loss"],
            "decline_p": b.get("decline_probability")}


# (raw dir, summary file, cases) — merged-tip rerun, OFF only.
PASSES = [
    ("raw-desay", "desay-2015"), ("raw-desay", "desay-2020"),
    ("raw-classic", "huawei"), ("raw-classic", "nokia"),
]


def main() -> None:
    out: dict = {}
    for raw_dir, case in PASSES:
        case_dir = os.path.join(HERE, raw_dir, case)
        summary_path = os.path.join(HERE, raw_dir, "summary.json")
        summary = json.load(open(summary_path))
        case_out = summary[case]
        print(f"\n===== PROFIT MC {raw_dir}/{case} =====", flush=True)
        result: dict = {}
        anchor_id = case_out.get("anchor_run_id")
        if anchor_id:
            result["anchor"] = run_profit_mc(
                case_dir, anchor_id, "03c-anchor-monte-carlo-profit",
                "10-anchor-replay.json")
        for arm_name, child_id in (case_out.get("child_run_ids") or {}).items():
            tag = tag_of(arm_name)
            step = f"06c-mc-profit-{tag}"
            result[arm_name] = run_profit_mc(
                case_dir, child_id, step, f"09-child-replay-{tag}.json")
        out[f"{raw_dir}/{case}"] = result
    with open(os.path.join(HERE, "profit-summary.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\nDONE. profit summary -> profit-summary.json", flush=True)


if __name__ == "__main__":
    main()
