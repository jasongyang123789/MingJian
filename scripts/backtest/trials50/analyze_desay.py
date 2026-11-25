#!/usr/bin/env python3
"""Desay ADAS-CHAIN (Track C1) analysis: trajectory bands + realized-arm
trajectories, share AND revenue (+ profit observed), the frozen-baseline
BACKLOG decomposition (B replay vs B-with-backlog_conversion=0 replay),
the frozen-baseline ADAS decomposition (B replay vs B-with-adas_coupling=0
AND adas_share_coupling=0 replay), and the before/after comparison
against the e047f50 re-run (the before-baseline).

- Anchor ensemble band at ticks 0/3/5: market_share across the 50 baseline
  trial runs of the anchor share ensemble (03), revenue across the 50 baseline
  trial runs of the anchor revenue ensemble (03b). Snapshots table, read-only.
- Realized arm point trajectory: child base run replay package; child tick t
  = anchor year t+1 (child tick 0 is the anchor tick-1 fork snapshot /
  resampled start; child tick 2 = year 3 mid-node, child tick 4 = year 5 target).
- Also prints per-arm ensembles + ES values (share, from 07 files) for the
  share-based most_robust cross-check.
- Frozen decomposition: step 13 replay (B, all variables pinned at B's
  sampled values, backlog_conversion=0) vs step 09 B replay; the difference
  at ticks 2/4 is the BACKLOG channel's marginal revenue contribution
  (NEV chain stays on in both).
- Frozen ADAS decomposition: step 13b replay (B, all variables pinned at
  B's sampled values, adas_coupling=0 AND adas_share_coupling=0) vs step
  09 B replay; the difference at ticks 2/4 is the ADAS channel's marginal
  revenue AND share contribution (NEV chain + backlog stay on in both).
- Before/after comparison: per-tick B-replay growth factors, the ADAS
  penetration trajectory, and yr-3 / yr-5 errors (replay + P50) vs
  actuals, before (e047f50 re-run numbers, hardcoded below with their
  report citation) vs after (this run).
"""
import json
import os
import sqlite3

import backtest_common  # shared config (run dir)

HERE = str(backtest_common.get_run_dir())
DB = str(backtest_common.get_db_path())
RAW = os.path.join(HERE, "raw-desay")

REALIZED = {
    "desay-2015": "B invest smart cockpit ADAS",
    "desay-2020": "B aggressive intelligent driving push",
}

# Scoring actuals (REPORT.md): year-3, year-4 and year-5 revenue, RMB m.
# ALIGNED-YEAR normal value (D2C, 2026-11-25, Ho-approved): the normal
# value is the B tick-4 P50 compared to the YEAR-4 actual (the horizon's
# last simulated year), replacing the one-year-ahead convention that
# compared tick-4 P50 to the year-5 actual. yr5 errors are kept below
# as legacy lines (labeled one-year-ahead), not scored.
ACTUALS = {
    "desay-2015": {"yr3": 5408.74, "yr4": 5337.0, "yr5": 6799.06},
    "desay-2020": {"yr3": 21908.0, "yr4": 27618.0, "yr5": 32557.18},
}

# BEFORE baseline — merged-tip rerun (backtest-rerun-merged-2026-11-23/
# REPORT.md §4–§5), identical to the profit-migration rerun for
# revenue/share (that rerun's revenue/share were bit-identical to the
# merged rerun; only profit moved, to the product path). The
# revenue/share before/after delta in THIS run isolates the A+C
# effect: Track C downside default ON (the harness passes no downside
# key, so the new default applies); the Track A intake anchor is a
# no-op for the harness's old Track 11 revenue term (it reads the
# pre-tick book only, not the intake), so any revenue/share move is
# C's shock, not A's anchor.
BEFORE = {
    "desay-2015": {"replay_yr3": 5828.7698, "replay_yr5": 9858.7436, "p50_yr5": 9070.8974},
    "desay-2020": {"replay_yr3": 19309.903, "replay_yr5": 47206.1176, "p50_yr5": 41069.1119},
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
    for case in ("desay-2015", "desay-2020"):
        mc = json.load(open(os.path.join(RAW, case, "03-anchor-monte-carlo.json")))["body"]
        mcr = json.load(open(os.path.join(RAW, case, "03b-anchor-monte-carlo-revenue.json")))["body"]
        trials = mc["trial_run_ids"]["baseline"]
        trials_r = mcr["trial_run_ids"]["baseline"]
        print(f"\n== {case} == anchor share trials n={len(trials)}, revenue trials n={len(trials_r)}")
        for tick in (0, 3, 5):
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
        traj_p = {s["tick"]: round(s["state"].get("profit", -1), 4) for s in pkg["snapshots"]}
        print(f"  realized arm '{arm_name}' child {child_id[:8]}")
        print(f"    share traj: {traj_s}")
        print(f"    revenue traj: {traj_r}")
        print(f"    profit traj: {traj_p}")
        print(f"    realized year3 (child tick2): share={traj_s.get(2)} revenue={traj_r.get(2)} profit={traj_p.get(2)}")
        print(f"    realized year5 (child tick4): share={traj_s.get(4)} revenue={traj_r.get(4)} profit={traj_p.get(4)}")
        for arm_file in sorted(os.listdir(os.path.join(RAW, case))):
            if arm_file.startswith("06-mc-"):
                suffix = arm_file[6:]
                b = json.load(open(os.path.join(RAW, case, arm_file)))["body"]["baseline"]
                br = json.load(open(os.path.join(RAW, case, "06b-mc-revenue-" + suffix)))["body"]["baseline"]
                es = json.load(open(os.path.join(RAW, case, "07-es-" + suffix)))["body"]
                print(f"  arm {suffix[:-5]}: share P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']} | "
                      f"revenue P50={br['p50']} P10={br['p10']} P90={br['p90']} p_loss={br['p_loss']} | ES={es}")
        # Frozen-baseline BACKLOG decomposition (steps 12-13): B replay vs
        # the frozen B-with-backlog_conversion=0 replay, same pinned base.
        frozen_path = os.path.join(RAW, case, "13-frozen-replay.json")
        if os.path.exists(frozen_path):
            frep = json.load(open(frozen_path))["body"]
            fpkg = frep["package"]
            if isinstance(fpkg, str):
                fpkg = json.loads(fpkg)
            f_traj_r = {s["tick"]: round(s["state"].get("revenue", -1), 4) for s in fpkg["snapshots"]}
            f_traj_s = {s["tick"]: round(s["state"].get("market_share", -1), 4) for s in fpkg["snapshots"]}
            print(f"  frozen B-no-backlog replay: revenue traj {f_traj_r}")
            for tick in (2, 4):
                base_r, froz_r = traj_r.get(tick), f_traj_r.get(tick)
                if base_r and froz_r:
                    print(f"    BACKLOG channel contribution tick{tick}: B {base_r} vs frozen {froz_r} "
                          f"(+{round(base_r - froz_r, 2)}, +{round(100 * (base_r / froz_r - 1), 1)}%)")
            print(f"    frozen share traj: {f_traj_s} (must equal B: backlog does not touch share)")
        # Frozen-baseline ADAS decomposition (steps 12b-13b): B replay vs
        # the frozen B-with-adas_coupling=0 AND adas_share_coupling=0
        # replay, same pinned base.
        frozen_adas_path = os.path.join(RAW, case, "13b-frozen-adas-replay.json")
        if os.path.exists(frozen_adas_path):
            farep = json.load(open(frozen_adas_path))["body"]
            fapkg = farep["package"]
            if isinstance(fapkg, str):
                fapkg = json.loads(fapkg)
            fa_traj_r = {s["tick"]: round(s["state"].get("revenue", -1), 4) for s in fapkg["snapshots"]}
            fa_traj_s = {s["tick"]: round(s["state"].get("market_share", -1), 4) for s in fapkg["snapshots"]}
            print(f"  frozen B-no-adas replay: revenue traj {fa_traj_r}")
            print(f"  frozen B-no-adas replay: share traj {fa_traj_s}")
            for tick in (2, 4):
                base_r, froz_r = traj_r.get(tick), fa_traj_r.get(tick)
                base_s, froz_s = traj_s.get(tick), fa_traj_s.get(tick)
                if base_r and froz_r:
                    print(f"    ADAS channel contribution tick{tick}: revenue B {base_r} vs frozen {froz_r} "
                          f"(+{round(base_r - froz_r, 2)}, +{round(100 * (base_r / froz_r - 1), 1)}%)")
                if base_s and froz_s:
                    print(f"    ADAS channel contribution tick{tick}: share B {base_s} vs frozen {froz_s} "
                          f"(+{round(base_s - froz_s, 4)}, +{round(100 * (base_s / froz_s - 1), 1)}%)")
        # ADAS penetration trajectory on the B replay.
        traj_a = {s["tick"]: round(s["state"].get("adas_penetration", -1), 4) for s in pkg["snapshots"]}
        print(f"  ADAS penetration traj (B replay): {traj_a}")
        # Shape comparison: B-replay growth factors, backlog term, and
        # yr-3/yr-5 errors before (e047f50) vs after (this run).
        traj_b = {s["tick"]: round(s["state"].get("order_backlog", -1), 4) for s in pkg["snapshots"]}
        factors = [round(traj_r[t] / traj_r[t - 1], 4) for t in (1, 2, 3, 4)]
        print(f"  SHAPE B-replay growth factors ticks1-4: {factors} "
              f"({'FALLING' if factors == sorted(factors, reverse=True) else 'NOT falling'})")
        print(f"  SHAPE backlog traj: {traj_b}")
        b_p50 = json.load(open(os.path.join(RAW, case, "06b-mc-revenue-" + tag + ".json")))["body"]["baseline"]
        before = BEFORE[case]
        act = ACTUALS[case]
        err3_before = 100 * (before["replay_yr3"] / act["yr3"] - 1)
        err3_after = 100 * (traj_r[2] / act["yr3"] - 1)
        err5_before = 100 * (before["p50_yr5"] / act["yr5"] - 1)
        err5_after = 100 * (b_p50["p50"] / act["yr5"] - 1)
        err5r_before = 100 * (before["replay_yr5"] / act["yr5"] - 1)
        err5r_after = 100 * (traj_r[4] / act["yr5"] - 1)
        print(f"  SHAPE yr3 replay error: BEFORE {err3_before:.1f}% -> AFTER {err3_after:.1f}%")
        print(f"  SHAPE yr5 P50 error:    BEFORE {err5_before:.1f}% -> AFTER {err5_after:.1f}% (B P50 {b_p50['p50']})")
        print(f"  SHAPE yr5 replay error: BEFORE {err5r_before:.1f}% -> AFTER {err5r_after:.1f}%")
        # ALIGNED-YEAR normal value (D2C, 2026-11-25): B tick-4 P50 vs
        # the YEAR-4 actual. The yr5 lines above are the legacy
        # one-year-ahead convention (kept for the record, not scored).
        # No BEFORE aligned value is recorded (the before run's tick-4
        # P50 was never saved), so only the AFTER aligned error prints.
        err4_after = 100 * (b_p50["p50"] / act["yr4"] - 1)
        err4r_after = 100 * (traj_r[4] / act["yr4"] - 1)
        print(f"  NORMAL-VALUE (aligned yr4) P50 error: {err4_after:.1f}% (B P50 {b_p50['p50']} vs yr4 actual {act['yr4']})")
        print(f"  NORMAL-VALUE (aligned yr4) replay error: {err4r_after:.1f}%")
        print(f"  SHAPE signed gap |e3-e5| P50: BEFORE {abs(err3_before - err5_before):.1f}pp -> AFTER {abs(err3_after - err5_after):.1f}pp")
        print(f"  SHAPE yr3/yr5 replay ratio: BEFORE {before['replay_yr3'] / before['replay_yr5']:.3f} -> AFTER {traj_r[2] / traj_r[4]:.3f} (actual {act['yr3'] / act['yr5']:.3f})")
    con.close()


if __name__ == "__main__":
    main()
