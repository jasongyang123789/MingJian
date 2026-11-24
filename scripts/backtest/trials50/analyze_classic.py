#!/usr/bin/env python3
"""Rerun analysis: trajectory bands + realized-arm trajectories, share AND revenue.

- Anchor ensemble band at ticks 0/5/10: market_share across the 50 baseline
  trial runs of the anchor share ensemble (03), revenue across the 50 baseline
  trial runs of the anchor revenue ensemble (03b). Snapshots table, read-only.
- Realized arm point trajectory: child base run replay package; child tick t
  = anchor year t+1 (child tick 0 is the anchor tick-1 fork snapshot).
- Also prints per-arm ensembles + ES values (share, from 07 files) for the
  share-based most_robust cross-check.
"""
import json
import os
import sqlite3

import backtest_common  # shared config (run dir)

HERE = str(backtest_common.get_run_dir())
DB = str(backtest_common.get_db_path())
RAW = os.path.join(HERE, "raw-classic")

REALIZED = {
    "huawei": "B 坚持投入",
    "nokia": "A 坚持Symbian",
}


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    f = i - lo
    return round(s[lo] * (1 - f) + s[hi] * f, 4)


def band(con, trials, field, tick):
    ph = ",".join("?" * len(trials))
    rows = con.execute(
        f"SELECT json_extract(state, '$.{field}') FROM state_snapshots "
        f"WHERE run_id IN ({ph}) AND tick = ?",
        (*trials, tick),
    ).fetchall()
    vals = [r[0] for r in rows if r[0] is not None]
    return {"n": len(vals), "p10": pct(vals, 0.1), "p50": pct(vals, 0.5), "p90": pct(vals, 0.9)}


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for case in ("huawei", "nokia"):
        mc = json.load(open(os.path.join(RAW, case, "03-anchor-monte-carlo.json")))["body"]
        mcr = json.load(open(os.path.join(RAW, case, "03b-anchor-monte-carlo-revenue.json")))["body"]
        trials = mc["trial_run_ids"]["baseline"]
        trials_r = mcr["trial_run_ids"]["baseline"]
        print(f"\n== {case} == anchor share trials n={len(trials)}, revenue trials n={len(trials_r)}")
        for tick in (0, 5, 10):
            print(f"  anchor band share   tick{tick}: {band(con, trials, 'market_share', tick)}")
            print(f"  anchor band revenue tick{tick}: {band(con, trials_r, 'revenue', tick)}")
        print(f"  anchor MC share final: P50={mc['baseline']['p50']} P10={mc['baseline']['p10']} P90={mc['baseline']['p90']} p_loss={mc['baseline']['p_loss']}")
        print(f"  anchor MC revenue final: P50={mcr['baseline']['p50']} P10={mcr['baseline']['p10']} P90={mcr['baseline']['p90']} p_loss={mcr['baseline']['p_loss']}")
        arm_name = REALIZED[case]
        ov = json.load(open(os.path.join(RAW, case, "05-override.json")))["body"]
        child_id = next(o["child_run_id"] for o in ov["outcomes"] if o["name"] == arm_name)
        tag = "".join(c if (c.isalnum() or c in "-_") else "_" for c in arm_name.replace(" ", "_"))
        rep = json.load(open(os.path.join(RAW, case, f"09-child-replay-{tag}.json")))["body"]
        pkg = rep["package"]
        if isinstance(pkg, str):
            pkg = json.loads(pkg)
        traj_s = {s["tick"]: round(s["state"].get("market_share", -1), 4) for s in pkg["snapshots"]}
        traj_r = {s["tick"]: round(s["state"].get("revenue", -1), 4) for s in pkg["snapshots"]}
        print(f"  realized arm '{arm_name}' child {child_id[:8]}")
        print(f"    share traj: {traj_s}")
        print(f"    revenue traj: {traj_r}")
        print(f"    realized year5 (child tick4): share={traj_s.get(4)} revenue={traj_r.get(4)}")
        print(f"    realized year10 (child tick9): share={traj_s.get(9)} revenue={traj_r.get(9)}")
        for arm_file in sorted(os.listdir(os.path.join(RAW, case))):
            if arm_file.startswith("06-mc-"):
                suffix = arm_file[6:]
                b = json.load(open(os.path.join(RAW, case, arm_file)))["body"]["baseline"]
                br = json.load(open(os.path.join(RAW, case, "06b-mc-revenue-" + suffix)))["body"]["baseline"]
                es = json.load(open(os.path.join(RAW, case, "07-es-" + suffix)))["body"]
                print(f"  arm {suffix[:-5]}: share P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']} | "
                      f"revenue P50={br['p50']} P10={br['p10']} P90={br['p90']} p_loss={br['p_loss']} | ES={es}")
    con.close()


if __name__ == "__main__":
    main()
