#!/usr/bin/env python3
"""Re-check the §9 profit-headline rule at trials=50.

Rule (backtest-scoring-rules.md §9): a case-arm profit decline_p enters
the headline iff decline_p >= 0.35 AND saturation category is
informative AND required_depth <= 0.35.

Inputs (all from THIS trials50 run, downside ON, seed 42):
- decline_p: the trials=50 profit MC baseline (03c anchor / 06c child
  files) for each B arm.
- category / required_depth: from the mode-path growth factors via
  planagent.services.simulation.downside_headline (imported from the
  trials50 worktree). The mode path is the deterministic NO-SHOCK
  trajectory.

D2C (2026-11-25): the seam-fix OFF reference no longer licenses the
mode path — D2C moved the simulation path, so the seam-fix OFF
factors (2015 B monotonically rising [1.0785, 1.2587, 1.2653, 1.2774])
are stale for this model. The OFF mode factors now come from the D2C
OFF probe (research/strategy-engine/
desay-2018-d2c-implementation-2026-11-25/rerun-2018/off-probe/
mode-paths.json), which re-derived them on the D2C backend (:8024,
same worktree, same code): anchor with downside None, B arm forked
at step 1, B child replay read back. The probe's Huawei/Nokia
categories reproduce the seam-fix values exactly (informative 0.2881
/ structural), validating the probe methodology; only the Desay
factors moved (the D2C schedule exposes the tick-1 margin dip).

Trials=20 ON decline_p values are hardcoded from the A/C + seam-fix
reports for the side-by-side.

Run with the repo worktree venv:
    <worktree>/.venv/bin/python score_headlines.py
"""
from __future__ import annotations

import json
import os

import backtest_common  # repo root on sys.path, shared config

from planagent.services.simulation.downside_headline import (  # noqa: E402
    assess_decline_saturation,
    max_window_rise_over_support,
)

HERE = str(backtest_common.get_run_dir())
# D2C OFF probe (same backend, same code — the mode-path source for
# this model). The seam-fix reference is retained only as history.
PROBE = os.path.expanduser(
    "~/workspace/research/strategy-engine/desay-2018-d2c-implementation-2026-11-25"
    "/rerun-2018/off-probe/mode-paths.json"
)

# (case, raw subdir, B arm name, trials=20 ON decline_p)
B_ARMS = [
    ("desay-2015", "desay", "B invest smart cockpit ADAS", 0.6),
    ("huawei", "classic", "B 坚持投入", 0.45),
    ("desay-2020", "desay", "B aggressive intelligent driving push", 0.0),
    ("nokia", "classic", "B 转向触屏生态", 1.0),
]

# Engine unified default (Track C, downside.py — read from the worktree
# module, never hardcoded; same values as the seam-fix analysis).
from planagent.services.simulation.downside import (  # noqa: E402
    DOWNSIDE_DEFAULT_DEPTH,
    DOWNSIDE_DEFAULT_DURATION,
)


def tag_of(arm_name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in arm_name.replace(" ", "_"))


def replay_factors(case_dir: str, arm: str, metric: str = "profit") -> list[float]:
    tag = tag_of(arm)
    path = os.path.join(case_dir, f"09-child-replay-{tag}.json")
    body = json.load(open(path))["body"]
    pkg = body.get("package")
    if isinstance(pkg, str):
        pkg = json.loads(pkg)
    traj = {}
    for snap in pkg.get("snapshots", []):
        value = (snap.get("state") or {}).get(metric)
        if value is not None:
            traj[int(snap["tick"])] = float(value)
    ticks = sorted(traj)
    return [traj[ticks[i + 1]] / traj[ticks[i]] for i in range(len(ticks) - 1)
            if traj[ticks[i]] != 0.0]


def main() -> None:
    depth_high = float(max(DOWNSIDE_DEFAULT_DEPTH))
    durations = tuple(sorted(float(d) for d in DOWNSIDE_DEFAULT_DURATION))
    max_rise = max_window_rise_over_support(durations)
    print(f"engine default: depth {tuple(DOWNSIDE_DEFAULT_DEPTH)}, "
          f"duration {tuple(DOWNSIDE_DEFAULT_DURATION)}, "
          f"depth_high={depth_high}, max_window_rise={max_rise:.3f}")
    probe = json.load(open(PROBE))
    out: dict = {}
    for case, sub, arm, dp20 in B_ARMS:
        case_dir = os.path.join(HERE, f"raw-{sub}", case)
        mc = json.load(open(os.path.join(
            case_dir, f"06c-mc-profit-{tag_of(arm)}.json")))["body"]
        assert mc["seed"] == 42 and mc["trials"] == 50, (case, mc["seed"], mc["trials"])
        dp50 = mc["baseline"].get("decline_probability")
        # Mode-path factors: the D2C OFF probe (same backend, same
        # code). The ON factors carry the shock and are NOT the mode
        # path; they are printed only as a cross-check that this run's
        # replays are the ones the probe's anchors were forked from
        # (same case specs, same seed).
        f_on = replay_factors(case_dir, arm)
        f_off = probe[case]["mode_profit_factors"]
        dec = assess_decline_saturation(f_off, depth_high, max_rise)
        assert dec.category == probe[case]["category"], (case, dec.category)
        assert (dec.required_depth is None) == (probe[case]["required_depth"] is None), case
        if dec.required_depth is not None:
            # The probe saved factors rounded to 4dp; recomputing from
            # them shifts the depth in the last digit — tolerance, not
            # bit equality.
            assert abs(dec.required_depth - probe[case]["required_depth"]) <= 5e-4, case
        rd = None if dec.required_depth is None else round(dec.required_depth, 4)
        headline = bool(dp50 is not None and dp50 >= 0.35
                        and dec.category == "informative"
                        and rd is not None and rd <= 0.35)
        out[f"{case} B profit"] = {
            "decline_p_trials20_on": dp20, "decline_p_trials50_on": dp50,
            "category": dec.category, "required_depth": rd,
            "headline": headline,
            "mode_growth_factors": [round(g, 4) for g in f_off],
            "on_growth_factors": [round(g, 4) for g in f_on],
        }
        print(f"{case} B profit: decline_p {dp20} (t20) -> {dp50} (t50) | "
              f"category={dec.category} required_depth={rd} | "
              f"HEADLINE {'IN' if headline else 'OUT'} "
              f"(OFF mode factors from the D2C probe; ON factors {[round(g, 4) for g in f_on]})")
    json.dump(out, open(os.path.join(HERE, "headline-check.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\nwrote headline-check.json")


if __name__ == "__main__":
    main()
