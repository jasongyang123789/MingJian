#!/usr/bin/env python3
"""Desay SV backtests on the AUTOMOTIVE pack + ORDER-BOOK mechanism
(e047f50 re-run, Track 11 protocol): desay-2015 (decide end-2015, project to 2020)
and desay-2020 (decide end-2020, project to 2025), re-wired from the
Track 7 auto-pack harness (run_desay_autopack.py, which is NOT
modified) with the Track 7 §7 order-book mechanism attached: the
revenue driver gains the backlog term (D2C, 2026-11-25:
+ backlog_delivery_fraction * order_backlog_opening / revenue — the
lag-shaped delivery schedule (0, 0.15, 0.45, 0.30, 0.10) of the
opening book, superseding the geometric
backlog_conversion * order_backlog / revenue), the intake flow
decays per tick, and the backlog stock updates by the scheduled
delivery. The NEV chain stays the level term; the
backlog term is the shape term. Own scratch backend (BACKTEST_BASE,
default :8024), own DB $BACKTEST_RUN_DIR/trials50-fbook.db; never
touches :8000/3000.

FIREWALL (hard): order-intake magnitudes come from decision-time
announcements ONLY — 2020: ~70亿 annualised new orders (≈1.0×
revenue); the 2021–2023 realized order path (>120/>200/>245亿) is
scoring/validation evidence ONLY, never an input. 2015: no order
surge was disclosed, so the intake rate is a small-book labeled
assumption (mode 0.25× revenue). The corporate-template scores in
REPORT.md are NOT rewritten; this run is labeled ORDER-BOOK
throughout. Success criterion (Track 7 §7) is SHAPE improvement
(yr-3 error and yr-5 error moving toward each other + per-tick
growth falling), NOT hitting both targets.

NEV transmission chain — diagnostic build spec (DIAGNOSTIC-2020.md
§5.2 / new-parameter.md §2), exact: 4 template variables
(nev_ceiling / nev_rate / nev_midpoint / nev_coupling) + the pack's
nev_penetration STATE field reused (no duplicate intermediate) + a
case-level logistic tick driver (output nev_penetration, replacing the
template's drift driver per-output at merge) + the revenue tick driver
gaining exactly one additive term
(+ nev_coupling * nev_penetration). No interaction terms; the share
formula is the corporate one, untouched. PROFIT MIGRATION (2026-11-23,
Ho 11:05): the case profit formula is REMOVED — the run now reads the
template's product profit path (profit = revenue x net_margin, R&D
decomposition), with the R&D leg levels bound per case below. NO
domain-controller substitution mechanism (diagnostic §5.1c: real but
secondary; superseded by the reconciliation instruction).

ADAS penetration chain (Track C1, gap audit §3 C1; full design in
TRACK-C1.md): the case gains a logistic tick driver (output
adas_penetration, replacing the template drift driver per-output at
merge) + the revenue driver gains exactly one additive term
(+ adas_coupling * adas_penetration) + the share driver gains exactly
one additive term (+ adas_share_coupling * adas_penetration).
Division of labor with disruptor_adoption / revenue_coupling (the
design precondition): adoption is BREADTH (any smart function,
L0-L2 combined), adas_penetration is GRADE (L2 within new cars);
the couplings price different hardware, so no double count. The
coupling mode (0.25) is set by analogy to nev_coupling, never from
the intelligent-driving segment's 10.48% revenue share. Profit was
untouched by the chain under the legacy decoupled driver; since the
2026-11-23 profit migration the chain reaches profit through the
template path (revenue carries the ADAS term, profit = revenue x
net_margin). A second frozen-baseline variant (B with
adas_coupling=0 AND adas_share_coupling=0, all else pinned) runs
after derive as steps 12b-13b; its replay isolates the ADAS
channel's marginal contribution (NEV + backlog stay on in both).

Modeling conventions (labeled; full audit in TRACK7-NEV-CHAIN.md):
- domain=automotive, actor_template=tier1_supplier, tick_count=5
  (1 tick = 1 year), seed 42 / trials 50, anchor seed 7.
- The pack is monthly-calibrated; the Desay case is yearly. The
  inventory channel is neutralized (retail == wholesale at the pack
  retail/spine ratio, dealer_inventory_coef pinned at the 1.2 neutral
  band) so the production spine stays at the case's annual value; the
  residual monthly-driver drift is second-order (<0.5% over 5 ticks)
  and is measured from the anchor replay, not assumed away.
- Arm rates set from DECISION-POINT reasoning only, never tuned to
  outcomes. The expected validation result (diagnostic §5.4) is B
  year-3 ~10201 / year-5 ~18212 at defensible values (planning path,
  k=0.25) — desay-2020 STILL FAILS, and that is the expected honest
  result. The post-hoc fitted couplings (9.69 / 2.08 planning path)
  are NEVER used as parameters.
- Decision-year full-year figures are decision-time INTERNAL figures
  (same caveats as REPORT.md). Post-decision actuals are scoring-only
  (firewall). The corporate-template scores in REPORT.md are NOT
  rewritten; this run is labeled ORDER-BOOK throughout (the AUTO-PACK
  run is the before-baseline for the shape comparison).

Usage: python3 run_desay.py [--case desay-2015|desay-2020|all] [--skip-derive]
Writes raw JSON per step to raw/<case>/ and a summary to summary.json.
A frozen-baseline decomposition variant (B with backlog_conversion=0, all
other variables pinned at B's sampled values — diagnostic Appendix A,
per channel) runs after derive as steps 12-13; its replay isolates the
BACKLOG channel's marginal contribution (the NEV chain stays on).
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
import urllib.error

import backtest_common  # repo root on sys.path, shared config

BASE = backtest_common.get_base()
OUT = str(backtest_common.get_run_dir() / "raw-desay")
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


def save(case: str, step: str, status: int, obj) -> None:
    d = os.path.join(OUT, case)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{step}.json"), "w") as f:
        json.dump({"http_status": status, "body": obj}, f, indent=2, ensure_ascii=False)


def triangular(min_v, mode, max_v):
    return {"type": "triangular", "min": min_v, "mode": mode, "max": max_v}


def chain_drivers():
    """Growth-coupled diffusion drivers + the NEV transmission chain
    (diagnostic build spec §5.2, exact).

    adoption = logistic(rate*(tick-midpoint), ceiling)
    nev_penetration = logistic(nev_rate*(tick-nev_midpoint), nev_ceiling)
        — writes to the pack's nev_penetration STATE field, replacing
        the template's drift driver per-output at merge; the dual-track
        split drivers then read the chain's penetration.
    adas_penetration = logistic(adas_rate*(tick-adas_midpoint), adas_ceiling)
        — writes to the pack's adas_penetration STATE field, replacing
        the template's drift driver per-output at merge (Track C1).
    share   = min(0.85, max(0, share*(1+base_growth + share_coupling*adoption
                              + adas_share_coupling*adas_penetration)))
    revenue = max(0, revenue*(1+revenue_growth + revenue_coupling*adoption
                              + nev_coupling*nev_penetration
                              + adas_coupling*adas_penetration))
        — exactly one additive NEV term and exactly one additive ADAS
        term; no interaction term.
    profit  = max(0, profit*(1+profit_growth + profit_coupling*adoption))
        — untouched by either chain.
    PROFIT MIGRATION (2026-11-23, Ho 11:05 order): the profit driver above
    is REMOVED from the returned list (see below). The case no longer
    overrides the template's profit driver, so the run reads the product
    profit path: profit = revenue x net_margin (R&D decomposition:
    net_margin = gross_margin - rd_intensity - other_share, plus the
    Tier-1 transmission term on gross_margin). The case binds the five
    R&D leg levels via _rd_wiring_variables() below — the template
    defaults are placeholders (gross 0.30 / rd 0.05 / other 0.05 -> net
    0.20); without the binding the product path would run on the generic
    margin. The profit_growth / profit_coupling VARIABLES and the arms'
    profit overrides are deliberately RETAINED (sampled but unread):
    deleting them would shift the sampling stream and move every
    revenue/share draw, breaking the bit-identical revenue control
    (tripwire re-check) for a cleanup with zero modeling content. A
    future cleanup may delete them, but only with a full re-baseline.
    Share and revenue drivers are untouched by this migration.
    """
    adoption = {
        "output": "disruptor_adoption",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "disruptor_rate"},
                        {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "disruptor_midpoint"}]},
                    ],
                },
                {"ref": "disruptor_ceiling"},
            ],
        },
        "description": "Smart-cockpit/ADAS adoption S-curve (logistic in tick); within-tick intermediate, not a state field.",
        "tick_driver": True,
    }
    nev_penetration = {
        "output": "nev_penetration",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "nev_rate"},
                        {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "nev_midpoint"}]},
                    ],
                },
                {"ref": "nev_ceiling"},
            ],
        },
        "description": "NEV penetration S-curve (diagnostic §5.2); reuses the pack's nev_penetration state field, replacing the template drift driver per-output at merge. Planning path at modes: 0.044/0.079/0.133/0.200 at ticks 1..4.",
        "tick_driver": True,
    }

    adas_penetration_driver = {
        "output": "adas_penetration",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "adas_rate"},
                        {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "adas_midpoint"}]},
                    ],
                },
                {"ref": "adas_ceiling"},
            ],
        },
        "description": "L2 penetration S-curve (Track C1, gap audit §3 C1); reuses the pack's adas_penetration state field, replacing the template drift driver per-output at merge. Planning path at 2020 modes: 0.1286/0.2157/0.325/0.4343/0.5214 at ticks 1..5 — tick 1 sits on the 12% anchor.",
        "tick_driver": True,
    }

    def _growth(field: str, growth: str, coupling: str, cap: bool, adas_share: bool = False) -> dict:
        inner = {
            "op": "multiply",
            "args": [
                {"ref": field},
                {
                    "op": "add",
                    "args": [
                        1,
                        {
                            "op": "add",
                            "args": [
                                {"ref": growth},
                                {
                                    "op": "add",
                                    "args": [
                                        {"op": "multiply", "args": [{"ref": coupling}, {"ref": "disruptor_adoption"}]},
                                        # Track C1: exactly one ADAS grade term on
                                        # share (share only — profit never gains it).
                                        {"op": "multiply", "args": [{"ref": "adas_share_coupling"}, {"ref": "adas_penetration"}]}
                                        if adas_share else {"op": "multiply", "args": [0, {"ref": "adas_penetration"}]},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        floored = {"op": "max", "args": [0, inner]}
        expr = {"op": "min", "args": [floored, 0.85]} if cap else floored
        return {
            "output": field,
            "expression": expr,
            "description": f"{field} grows at {growth} plus {coupling} * adoption" + (" plus adas_share_coupling * adas_penetration (Track C1 grade term)" if adas_share else "") + "; floored at 0" + ("; capped at 0.85." if cap else "."),
            "tick_driver": True,
        }

    revenue = {
        "output": "revenue",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "revenue"},
                        {
                            "op": "add",
                            "args": [
                                1,
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "revenue_growth"},
                                        {
                                            "op": "add",
                                            "args": [
                                                {"op": "multiply", "args": [{"ref": "revenue_coupling"}, {"ref": "disruptor_adoption"}]},
                                                {
                                                    "op": "add",
                                                    "args": [
                                                        {"op": "multiply", "args": [{"ref": "nev_coupling"}, {"ref": "nev_penetration"}]},
                                                        {
                                                            "op": "add",
                                                            "args": [
                                                                # Track C1: exactly one ADAS grade
                                                                # term — the INCREMENTAL L2 premium
                                                                # stack only (NOT the segment's
                                                                # revenue share; that would
                                                                # double-count revenue_coupling).
                                                                {"op": "multiply", "args": [{"ref": "adas_coupling"}, {"ref": "adas_penetration"}]},
                                                                # D2C (2026-11-25): exactly one backlog
                                                                # term — the SHAPE term. Delivered
                                                                # amount = this tick's fraction of the
                                                                # OPENING book (0 in tick 1: the SOP-lag
                                                                # floor). The downturn brake adds
                                                                # downturn_brake * (tick == 1) — tick-1
                                                                # growth only; 0 for growth-year anchors.
                                                                {"op": "add", "args": [{"op": "multiply", "args": [{"ref": "backlog_delivery_fraction"}, {"op": "divide", "args": [{"ref": "order_backlog_opening"}, {"ref": "revenue"}]}]}, {"op": "multiply", "args": [{"ref": "downturn_brake"}, {"op": "max", "args": [0, {"op": "min", "args": [1, {"op": "subtract", "args": [2, {"ref": "tick"}]}]}]}]}]},
                                                            ],
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Revenue grows at revenue_growth plus revenue_coupling * adoption plus nev_coupling * nev_penetration (diagnostic §5.2) plus adas_coupling * adas_penetration (Track C1 §2: the grade term) plus backlog_delivery_fraction * order_backlog_opening / revenue (D2C §7: the shape term — lag-shaped delivery of the opening book) plus downturn_brake * (tick == 1) (D2C: tick-1 growth brake, 0 for growth-year anchors); floored at 0.",
        "tick_driver": True,
    }

    # Track 11 — order-book drivers. Order in this list is load-bearing:
    # revenue (above) reads the PRE-tick backlog; the intake driver then
    # decays the flow; the backlog driver then updates the stock from
    # the pre-tick backlog + the decayed intake - the converted amount.
    order_intake_decay = {
        "output": "order_intake",
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "order_intake"},
                {"op": "subtract", "args": [1, {"ref": "order_decay"}]},
            ],
        },
        "description": "New-orders flow decays by (1 - order_decay) per tick (Track 11 §7).",
        "tick_driver": True,
    }
    # D2C (2026-11-25) PROMOTED — scheduled-book depletion now lives
    # in the TEMPLATE (order_backlog merge anchor right after the
    # revenue passthrough, B' = max(0, B - backlog_delivery_fraction
    # * order_backlog_opening), plus the backlog_delivery_fraction
    # driver before the revenue passthrough). The case driver that the
    # experiment carried is DELIBERATELY DROPPED here: a case driver
    # on the same output would replace the anchor in place. The
    # revenue term is the D2C form (+ f*opening/R, 0 in tick 1, plus
    # the tick-1 brake); the intake driver still decays the diagnostic
    # flow.
    return [
        adoption,
        nev_penetration,
        adas_penetration_driver,
        _growth("market_share", "base_growth", "share_coupling", cap=True, adas_share=True),
        revenue,
        # PROFIT MIGRATION (2026-11-23): NO profit driver here anymore.
        # The template's profit tick driver (profit = revenue x net_margin)
        # survives the per-output merge and is the product profit path.
        # (The decoupled _growth("profit", ...) driver that used to sit
        # here is deleted, not commented out: a stale driver would still
        # override the template at merge time.)
        order_intake_decay,
        # NO order_backlog_update driver here — the template anchor
        # governs (see the comment above).
    ]


CASES = {
    "desay-2015": {
        "company_id": "backtest-desay-2015",
        "company_name": "Desay SV (2015 retrospective)",
        "market": "auto-electronics-china",
        "decision_time": "2015-12-31T00:00:00Z",
        "loss_threshold": 0.30,
        "revenue_loss_threshold": 3668.25,
        "formulas": chain_drivers(),
        "topic": "德赛西威2015：投智能座舱+ADAS，还是守传统导航/娱乐硬件？",
        "decomposition": {
            "topic": "德赛西威2015：投智能座舱+ADAS，还是守传统导航/娱乐硬件？",
            "root": {
                "name": "德赛西威2015：智能座舱来了，怎么选",
                "scope": ["smart", "traditional", "overseas"],
                "children": [
                    {"name": "智能化", "scope": ["smart"]},
                    {"name": "传统", "scope": ["traditional"]},
                    {"name": "出海与后市场", "scope": ["overseas"]},
                ],
            },
        },
        "variables": [
            {
                "id": "market_share",
                "unit": "share",
                "distribution": triangular(0.25, 0.30, 0.35),
                "evidence_ref": "estimate: LABELED ASSUMPTION — Tianfeng 2017-12-27: >30% of the domestic-made front-fit head-unit market in 2016 (head-unit revenue ~RMB 1.7bn vs ~RMB 6bn domestic market); broker estimate, not audited; 2016 figure carried to end-2015",
                "description": "中国前装车机市场份额（起始值，国内厂商口径）",
                "scope_tags": ["smart"],
            },
            {
                "id": "base_growth",
                "unit": "per-year",
                "distribution": triangular(-0.02, 0.02, 0.05),
                "evidence_ref": "estimate: labeled assumption — underlying share growth absent smart-cockpit adoption; domestic Tier-1 only ~22% of the total front-fit head-unit market in 2016 (Tianfeng), foreign/JV Tier-1s dominate",
                "description": "无智能座舱采用时的年均份额增长率",
                "scope_tags": ["traditional"],
            },
            {
                "id": "disruptor_ceiling",
                "unit": "share",
                "distribution": triangular(0.7, 0.85, 0.95),
                "evidence_ref": "estimate: LABELED ASSUMPTION — smart cockpit / ADAS eventually fitted in ~85% of new cars; 2015 front-fit nav penetration only 15.15% (3.712m / 24.6m sales), headroom large",
                "description": "智能座舱/ADAS 采用率饱和水平 K",
                "scope_tags": ["smart"],
            },
            {
                "id": "disruptor_rate",
                "unit": "per-year",
                "distribution": triangular(0.6, 0.8, 1.0),
                "evidence_ref": "estimate: LABELED ASSUMPTION — logistic steepness, slower than smartphones (Nokia recipe 1.2): auto model cycles run multi-year, cockpit redesigns follow model years",
                "description": "智能座舱/ADAS 采用 logistic 曲线陡峭度 r",
                "scope_tags": ["smart"],
            },
            {
                "id": "disruptor_midpoint",
                "unit": "years",
                "distribution": triangular(3.0, 4.0, 5.0),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption passes K/2 ~4 years out (2019); reasoning: 2015 nav penetration 15.15%, centre screens >70% (own-brand) by 2017 but nav-capable screens only ~20%, full smart cockpit several years out",
                "description": "智能座舱/ADAS 采用率过半的时点（tick）",
                "scope_tags": ["smart"],
            },
            {
                "id": "share_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.15, 0.25, 0.35),
                "evidence_ref": "estimate: LABELED ASSUMPTION — each unit of smart-cockpit adoption adds ~0.25 to the share growth rate per tick for a participating supplier",
                "description": "每单位采用率对份额增长率的提升系数",
                "scope_tags": ["smart"],
            },
            {
                "id": "revenue",
                "unit": "RMB m",
                "distribution": triangular(3200, 3668.25, 4100),
                "evidence_ref": "evidence: 2015 revenue RMB 3,668.25m (audited, prospectus disclosure chain — Guoxin sponsor letter 2017-12-25; decision-time INTERNAL figure, first published 2017, see REPORT.md provenance caveat)",
                "description": "年营业收入，单位百万元人民币（起始值）",
                "scope_tags": ["traditional"],
            },
            {
                "id": "revenue_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.10, 0.25),
                "evidence_ref": "estimate: 2013-2015 revenue CAGR ~43.5% (RMB 1.78bn→3.67bn) heavily discounted for a sustained 5-year rate; CAAM 2015 sales growth slowed to +4.68%, 1.6L purchase-tax cut was a one-off stimulus",
                "description": "无采用时的年均收入增长率",
                "scope_tags": ["traditional"],
            },
            {
                "id": "revenue_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.10, 0.15, 0.25),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption uplift on revenue; qualitative support only: smart-cockpit package value RMB 7,000-15,000 vs traditional ~RMB 2,000 (forward estimate, not a 2015 realised price)",
                "description": "每单位采用率对收入增长率的提升系数",
                "scope_tags": ["smart"],
            },
            {
                "id": "profit",
                "unit": "RMB m",
                "distribution": triangular(300, 358.87, 420),
                "evidence_ref": "evidence: 2015 net profit attributable to parent RMB 358.87m (audited, prospectus chain; decision-time INTERNAL figure, first published 2017, see REPORT.md provenance caveat)",
                "description": "年归母净利润，单位百万元人民币（起始值）",
                "scope_tags": ["traditional"],
            },
            {
                "id": "profit_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.08, 0.20),
                "evidence_ref": "estimate: labeled assumption, tracks revenue growth at a lower mode (margin pressure; 2015 gross margin 26.96%, peer band 24-27%)",
                "description": "无采用时的年均利润增长率",
                "scope_tags": ["traditional"],
            },
            {
                "id": "profit_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.05, 0.10, 0.20),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption uplift on profit, below revenue coupling (new-business investment + price pressure)",
                "description": "每单位采用率对利润增长率的提升系数",
                "scope_tags": ["smart"],
            },
        ],
        "internal": {
            "decision_point": "2015-12-31, 德赛西威上市前夜（2017-12-26上市）",
            "revenue_2015": "营业收入36.68亿（+39.12%），归母净利润3.59亿（+116.81%），毛利率26.96%",
            "segments_2015": "车载娱乐系统>50%营收，车载信息系统升至~30%，两者合计>80%；空调控制器、驾驶显示各<10%",
            "customers_2015": "马自达海外6.27亿（17%），一汽大众3.22亿（8.8%）；前五大客户含上汽通用五菱、长城、广汽自主",
            "market_2015": "中国汽车销量2459.76万辆（+4.68%）；前装导航渗透率15.15%（371.2万台）；新能源销量33.1万辆（首超1%）；Tesla Autopilot v7.0 2015年10月首发",
            "adas_2015": "ADAS尚处研发/ pre-revenue：2D全景泊车已量产上凯迪拉克，车道偏离/盲区/行人检测在研；毫米波雷达与ADAS工厂是IPO募投计划（2017），非2015年实际",
        },
        "arms": [
            {"name": "A stay traditional", "overrides": {"base_growth": 0.01, "share_coupling": 0.05, "revenue_growth": 0.06, "revenue_coupling": 0.02, "profit_growth": 0.05, "profit_coupling": 0.02}, "arm": "baseline", "mece_branches": ["传统"], "resample_variables": True},
            {"name": "B invest smart cockpit ADAS", "overrides": {"base_growth": 0.03, "share_coupling": 0.25, "revenue_growth": 0.10, "revenue_coupling": 0.15, "profit_growth": 0.08, "profit_coupling": 0.10}, "arm": "baseline", "mece_branches": ["智能化"], "resample_variables": True},
            {"name": "C expand overseas aftermarket", "overrides": {"base_growth": 0.02, "share_coupling": 0.10, "revenue_growth": 0.08, "revenue_coupling": 0.06, "profit_growth": 0.06, "profit_coupling": 0.05}, "arm": "baseline", "mece_branches": ["出海与后市场"], "resample_variables": True},
        ],
    },
    "desay-2020": {
        "company_id": "backtest-desay-2020",
        "company_name": "Desay SV (2020 retrospective)",
        "market": "auto-electronics-china",
        "decision_time": "2020-12-31T00:00:00Z",
        "loss_threshold": 0.066,
        "revenue_loss_threshold": 6799.06,
        "formulas": chain_drivers(),
        "topic": "德赛西威2020：加码智能驾驶+座舱域控，还是稳守座舱/适度投入？",
        "decomposition": {
            "topic": "德赛西威2020：加码智能驾驶+座舱域控，还是稳守座舱/适度投入？",
            "root": {
                "name": "德赛西威2020：智能驾驶来了，怎么选",
                "scope": ["driving", "cockpit", "connected"],
                "children": [
                    {"name": "智能驾驶", "scope": ["driving"]},
                    {"name": "座舱", "scope": ["cockpit"]},
                    {"name": "网联与出海", "scope": ["connected"]},
                ],
            },
        },
        "variables": [
            {
                "id": "market_share",
                "unit": "share",
                "distribution": triangular(0.05, 0.066, 0.08),
                "evidence_ref": "estimate: LABELED ASSUMPTION (derived) — Desay 2020 smart-cockpit revenue RMB 5,912m / GGAI estimate of the 2020 China smart-cockpit electronics market (>RMB 90bn) = 6.6%; market size is an estimate and a lower bound, so 6.6% is an upper-ish estimate",
                "description": "中国智能座舱电子市场份额（起始值，座舱收入/市场规模）",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "base_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.03, 0.06),
                "evidence_ref": "estimate: labeled assumption — underlying share growth absent intelligent-driving adoption; cockpit already 86.95% of revenue and growing +33.5% in 2020. Labeled assumption: the cited +33.5% is cockpit segment revenue growth including adoption effects, while this variable is share growth absent adoption, so its mode sits deliberately below the cited segment rate.",
                "description": "无智能驾驶采用时的年均份额增长率",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "disruptor_ceiling",
                "unit": "share",
                "distribution": triangular(0.7, 0.85, 0.95),
                "evidence_ref": "estimate: LABELED ASSUMPTION — intelligent-driving / cockpit-domain-controller penetration of new cars eventually ~85%",
                "description": "智能驾驶/座舱域控采用率饱和水平 K",
                "scope_tags": ["driving"],
            },
            {
                "id": "disruptor_rate",
                "unit": "per-year",
                "distribution": triangular(0.8, 1.0, 1.2),
                "evidence_ref": "estimate: LABELED ASSUMPTION — logistic steepness, faster than 2015 (0.8): NEV already scaling, State Council NEV plan (Nov 2020) targets 20% NEV share by 2025",
                "description": "智能驾驶采用 logistic 曲线陡峭度 r",
                "scope_tags": ["driving"],
            },
            {
                "id": "disruptor_midpoint",
                "unit": "years",
                "distribution": triangular(2.0, 3.0, 4.0),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption passes K/2 ~3 years out (2023); reasoning: 2020 NEV penetration 5.4% with a 20%-by-2025 state target, L2 fitment ~12%, combined driving-assist fitment 16.2%",
                "description": "智能驾驶采用率过半的时点（tick）",
                "scope_tags": ["driving"],
            },
            {
                "id": "share_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.15, 0.25, 0.35),
                "evidence_ref": "estimate: LABELED ASSUMPTION — each unit of intelligent-driving adoption adds ~0.25 to the share growth rate per tick for a participating supplier",
                "description": "每单位采用率对份额增长率的提升系数",
                "scope_tags": ["driving"],
            },
            {
                "id": "revenue",
                "unit": "RMB m",
                "distribution": triangular(6200, 6799.06, 7400),
                "evidence_ref": "evidence: FY2020 revenue RMB 6,799.06m (2020 annual-report summary, announcement 2021-010; decision-time INTERNAL figure, published 13 Apr 2021, see REPORT.md provenance caveat)",
                "description": "年营业收入，单位百万元人民币（起始值）",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "revenue_growth",
                "unit": "per-year",
                "distribution": triangular(0.05, 0.15, 0.30),
                "evidence_ref": "estimate: 2020 revenue +27.39% was a recovery year after 2018 -10.0% and 2019 -1.3%; mode 15% discounts it for a sustained 5-year rate; support: new project orders ~RMB 7.0bn annualised (~one full year of revenue), cockpit +33.5% and intelligent driving +94.78% in 2020",
                "description": "无采用时的年均收入增长率",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "revenue_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.15, 0.25, 0.35),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption uplift on revenue; intelligent-driving revenue grew +94.78% in 2020 off a small base (RMB 712m, 10.48%)",
                "description": "每单位采用率对收入增长率的提升系数",
                "scope_tags": ["driving"],
            },
            {
                "id": "profit",
                "unit": "RMB m",
                "distribution": triangular(450, 518.15, 600),
                "evidence_ref": "evidence: FY2020 net profit attributable to parent RMB 518.15m (2020 annual-report summary; decision-time INTERNAL figure, published 13 Apr 2021, see REPORT.md provenance caveat)",
                "description": "年归母净利润，单位百万元人民币（起始值）",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "profit_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.12, 0.25),
                "evidence_ref": "estimate: labeled assumption, tracks revenue growth at a lower mode (margin pressure; gross margin 23.39% in 2020, down from 25.78% in 2017). Labeled assumption: the lower mode is a deliberate discount for margin pressure, not an unexplained discount.",
                "description": "无采用时的年均利润增长率",
                "scope_tags": ["cockpit"],
            },
            {
                "id": "profit_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.10, 0.15, 0.25),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption uplift on profit, below revenue coupling (domain-controller investment + price pressure)",
                "description": "每单位采用率对利润增长率的提升系数",
                "scope_tags": ["driving"],
            },
        ],
        "internal": {
            "decision_point": "2020-12-31, 三大业务群成型之年",
            "revenue_2020": "营业收入67.99亿（+27.39%），归母净利润5.18亿（+77.36%），毛利率23.39%，研发8.17亿（12.02%）",
            "segments_2020": "智能座舱59.12亿（86.95%，+33.52%），智能驾驶7.12亿（10.48%，+94.78%），网联服务及其他1.75亿（2.57%，+65.10%）",
            "milestones_2020": "IPU03自动驾驶域控制器在小鹏P7量产；IPU04（英伟达Orin）与理想战略合作、目标2022年量产；360全景环视出货量中国第2；新获项目订单年化约70亿",
            "market_2020": "中国汽车销量2531.1万辆（-1.9%）；新能源销量136.7万辆，渗透率5.4%；国务院《新能源汽车产业发展规划（2021-2035）》：2025年新能源占比~20%；L2装配率~12%，L0-L2合计~34%",
            "context_2020": "2018-2019为下行周期（收入-10.0%/-1.3%，利润-32.5%/-29.8%），2020年为恢复年，非2013-2016增长线的延续",
        },
        "arms": [
            {"name": "A moderate cockpit focused", "overrides": {"base_growth": 0.02, "share_coupling": 0.10, "revenue_growth": 0.10, "revenue_coupling": 0.10, "profit_growth": 0.08, "profit_coupling": 0.08}, "arm": "baseline", "mece_branches": ["座舱"], "resample_variables": True},
            {"name": "B aggressive intelligent driving push", "overrides": {"base_growth": 0.03, "share_coupling": 0.25, "revenue_growth": 0.15, "revenue_coupling": 0.25, "profit_growth": 0.12, "profit_coupling": 0.15}, "arm": "baseline", "mece_branches": ["智能驾驶"], "resample_variables": True},
            {"name": "C connected services overseas", "overrides": {"base_growth": 0.02, "share_coupling": 0.15, "revenue_growth": 0.10, "revenue_coupling": 0.15, "profit_growth": 0.08, "profit_coupling": 0.10}, "arm": "baseline", "mece_branches": ["网联与出海"], "resample_variables": True},
        ],
    },
}


def _autopack_wiring_variables(production_mode: float, nev_pen: tuple, base_tag: str,
                               nev_path: tuple | None = None) -> list:
    """Auto-pack wiring variables appended to each Desay case.

    - production_volume: the ANNUAL volume spine (10k vehicles/year;
      the pack default is monthly). Triangular around the decision-time
      CAAM sales figure (published the following January; same
      internal-figure caveat as the FY revenue in REPORT.md).
    - sales_volume_retail == sales_volume_wholesale at the pack's
      retail/spine ratio (197.9/287.8), and dealer_inventory_coef at
      the 1.2 neutral band: this NEUTRALIZES the monthly inventory
      channel, which has no yearly meaning in this case. The values
      feed only second-order drift (<0.5% of production over 5 ticks);
      they are not scored.
    - nev_penetration: the decision-time starting level (2015: 33.1万
      NEV / 2459.76万 sales = 1.35%; 2020: 5.4%). The tick-1+ path is
      the chain logistic, not this value.
    - nev_path (2015 only): the 2015 decision-time outlook for the
      chain logistic. The template defaults (0.40/0.70/4.0) encode the
      2020 plan (20% by 2025), which did not exist in 2015; the 2015
      outlook is a labeled assumption anchored to the 2012-2020 NEV
      plan's ambition (5M cumulative by 2020) and 2015's observed NEV
      growth from a tiny base.
    """
    retail = round(production_mode * 197.9 / 287.8, 1)
    variables = [
        {
            "id": "production_volume",
            "unit": "10k vehicles/year",
            "distribution": triangular(production_mode - 150, production_mode, production_mode + 150),
            "evidence_ref": "evidence: CAAM annual sales (decision-time internal figure, published the following January; same caveat as FY revenue in REPORT.md)",
            "description": "年汽车销量/产量（体积主干，年口径；包默认值为月度）",
            "scope_tags": [base_tag],
        },
        {
            "id": "sales_volume_retail",
            "unit": "10k vehicles/year",
            "distribution": {"type": "fixed", "value": retail},
            "evidence_ref": "neutralization: pack monthly retail/spine ratio (197.9/287.8) applied to the annual spine; feeds only the neutralized inventory channel",
            "description": "年零售量（与批发量相等，中和库存通道）",
            "scope_tags": [base_tag],
        },
        {
            "id": "sales_volume_wholesale",
            "unit": "10k vehicles/year",
            "distribution": {"type": "fixed", "value": retail},
            "evidence_ref": "neutralization: equals retail, so the inventory driver adds ~0",
            "description": "年批发量（与零售量相等，中和库存通道）",
            "scope_tags": [base_tag],
        },
        {
            "id": "dealer_inventory_coef",
            "unit": "coefficient",
            "distribution": {"type": "fixed", "value": 1.2},
            "evidence_ref": "neutralization: the 1.2 reasonable-band ceiling is the production driver's no-op point",
            "description": "经销商库存系数（中和值，生产驱动因子为 1.0）",
            "scope_tags": [base_tag],
        },
        {
            "id": "nev_penetration",
            "unit": "rate",
            "distribution": triangular(*nev_pen),
            "evidence_ref": "evidence: NEV share of total auto sales at the decision date (2015: 33.1万/2459.76万 = 1.35%; 2020: 136.7万/2531.1万 = 5.4%; full-year prints published the following January)",
            "description": "新能源渗透率起始值（tick-1 起由链 logistic 接管）",
            "scope_tags": ["smart"] if base_tag == "traditional" else ["driving"],
        },
    ]
    if nev_path is not None:
        ceiling, rate, midpoint = nev_path
        variables += [
            {
                "id": "nev_ceiling",
                "unit": "share (0-1)",
                "distribution": triangular(*ceiling),
                "evidence_ref": "estimate: LABELED ASSUMPTION — 2015 outlook: no 2025 plan target existed yet; ceiling below the 2020-calibrated 0.40, anchored to the 2012-2020 NEV plan's 5M-cumulative-by-2020 ambition",
                "description": "NEV 渗透率长期饱和水平 K（2015 年展望）",
                "scope_tags": ["smart"],
            },
            {
                "id": "nev_rate",
                "unit": "per-year",
                "distribution": triangular(*rate),
                "evidence_ref": "estimate: LABELED ASSUMPTION — 2015 outlook: slower than the 2020-calibrated 0.70; NEV grew from a tiny base (33.1万辆) with no national 2025 target in force",
                "description": "NEV 渗透率 logistic 陡峭度 r（2015 年展望）",
                "scope_tags": ["smart"],
            },
            {
                "id": "nev_midpoint",
                "unit": "years (tick)",
                "distribution": triangular(*midpoint),
                "evidence_ref": "estimate: LABELED ASSUMPTION — 2015 outlook: midpoint later than the 2020-calibrated 4.0; the 2012-2020 plan's horizon ran to 2020, not 2025",
                "description": "NEV 渗透率过半时点（2015 年展望）",
                "scope_tags": ["smart"],
            },
        ]
    return variables



def _adas_wiring_variables(adas_pen: tuple, adas_midpoint: tuple | None, base_tag: str) -> list:
    """Track C1 ADAS wiring variables appended to each Desay case.

    - adas_penetration: the decision-time starting L2 level. 2020:
      triangular(0.11, 0.12, 0.16) — the decision-time-knowable range
      was 11-16% (evidence-2020 §1.4 verdict); the 12% mode is the
      Canalys Q4-2020 China L2 share (published Mar 2021, describing
      Q4 2020). 2015: triangular(0.00, 0.01, 0.02) — L2 was ~0 in
      2015 (Tesla Autopilot v7.0 launched Oct 2015; Desay ADAS still
      R&D/pre-revenue). The tick-1+ path is the chain logistic, not
      this value.
    - adas_midpoint (2015 only): the 2015 decision-time outlook for
      the chain logistic. The template defaults (0.65/0.70/3.0) encode
      the 2020 outlook; the 2015 outlook pushes the midpoint later
      (mode 5.0), mirroring the nev_path override pattern. Ceiling /
      rate / coupling stay at the template defaults in both cases.
    - adas_share_coupling: the GRADE channel's share elasticity,
      case-level only (like share_coupling — the template carries no
      share coupling for any chain). Triangular(0.10, 0.20, 0.30):
      mode 0.20 sits below share_coupling's 0.25 — the grade effect
      on share is weaker than the broad adoption effect. LABELED
      ASSUMPTION.
    FIREWALL: the MIIT 16.2% -> 64.9% realized diffusion series is
    scoring/validation context ONLY, never an input here — the case
    path is the decision-time logistic, not the realized path.
    """
    variables = [
        {
            "id": "adas_penetration",
            "unit": "rate",
            "distribution": triangular(*adas_pen),
            "evidence_ref": "evidence: L2 fitment at the decision date — 2020: Canalys Q4-2020 China L2 share 12% (published 2021-03-25/26; decision-time-knowable range 11-16%, evidence-2020 §1.4); 2015: ~0 (Tesla Autopilot v7.0 Oct 2015; Desay ADAS R&D/pre-revenue)",
            "description": "L2 渗透率起始值（tick-1 起由链 logistic 接管）",
            "scope_tags": ["driving"] if base_tag != "traditional" else ["smart"],
        },
        {
            "id": "adas_share_coupling",
            "unit": "per-unit-penetration",
            "distribution": triangular(0.10, 0.20, 0.30),
            "evidence_ref": "estimate: LABELED ASSUMPTION — each unit of L2 penetration adds ~0.20 to the share growth rate per tick for a participating supplier; below share_coupling's 0.25 (the grade effect on share is weaker than the broad adoption effect)",
            "description": "每单位 L2 渗透率对份额增长率的提升系数（等级通道，case 层）",
            "scope_tags": ["driving"] if base_tag != "traditional" else ["smart"],
        },
    ]
    if adas_midpoint is not None:
        variables.append(
            {
                "id": "adas_midpoint",
                "unit": "years (tick)",
                "distribution": triangular(*adas_midpoint),
                "evidence_ref": "estimate: LABELED ASSUMPTION — 2015 outlook: midpoint later than the 2020-calibrated 3.0; L2 was ~0 in 2015 and the grade curve had not started",
                "description": "L2 渗透率过半时点（2015 年展望）",
                "scope_tags": ["smart"],
            }
        )
    return variables


def _orderbook_wiring_variables(intake_rate: tuple, book_value: float, base_tag: str) -> list:
    """Track 11 order-book wiring variables appended to each Desay case.

    - order_backlog / order_intake: FIXED at one year of intake
      (intake-rate mode x mode revenue) — the opening stock proxy is a
      LABELED ASSUMPTION (the order stock itself was never disclosed).
      Bound as variables, not initial formulas: merge is per-output, so
      an initial formula and a tick driver cannot share an output id.
    - order_backlog_opening (D2C, 2026-11-25): FIXED at the same
      book_value — the frozen tick-0 level the delivery schedule
      delivers fractions of. The template's backlog_delivery_fraction
      driver reads it; the stock update drains the same amount.
    - downturn_brake (D2C, 2026-11-25): FIXED at 0.0 for the 2015 /
      2020 cases (anchor-year growth positive — no brake). The 2018
      case binds -0.1501 in its own script (anchor-year -10.01% minus
      revenue_growth mode +5%).
    - order_intake_rate: triangular around the decision-time order
      book. 2020: ~70亿 annualised new orders / 67.99亿 revenue ≈ 1.03
      → triangular(0.80, 1.00, 1.20). 2015: no order surge disclosed →
      triangular(0.15, 0.25, 0.40), a small-book labeled assumption.
      FIREWALL: the 2021–2023 realized order path (>120/>200/>245亿)
      is NEVER an input here — scoring evidence only.
    - backlog_conversion / order_decay: the template distributions
      (triangular(0.30, 0.40, 0.60) / triangular(0.10, 0.25, 0.40)),
      restated at case level with their decision-time basis. D2C:
      backlog_conversion is now the delivery schedule's on/off gate
      (1 on its whole support, 0 when frozen off), not a per-tick
      rate — retained as a sampled variable so the sampling stream is
      unchanged.
    """
    return [
        {
            "id": "order_backlog",
            "unit": "RMB m",
            "distribution": {"type": "fixed", "value": book_value},
            "evidence_ref": "estimate: LABELED ASSUMPTION — opening order-book stock = one year of intake at the intake-rate mode (the stock itself was never disclosed; 2020: 1.00 x 6799.06; 2015: 0.25 x 3668.25)",
            "description": "期初未交付订单存量（一年新签订单量的代理值，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "order_backlog_opening",
            "unit": "RMB m",
            "distribution": {"type": "fixed", "value": book_value},
            "evidence_ref": "estimate: LABELED ASSUMPTION — opening order-book stock, same proxy as order_backlog (D2C delivery schedule delivers fractions of this frozen tick-0 level)",
            "description": "期初订单存量（冻结的 tick-0 水平，交付计划的分母）",
            "scope_tags": [base_tag],
        },
        {
            "id": "downturn_brake",
            "unit": "per-year (additive growth points)",
            "distribution": {"type": "fixed", "value": 0.0},
            "evidence_ref": "rule: D2C downturn brake (2026-11-25, Ho-approved Option A) — anchor-year realized revenue growth is positive for 2015/2020, so no brake (0.0); the 2018 case binds -0.1501 in its own script",
            "description": "下行刹车（tick-1 增速修正；2015/2020 为 0）",
            "scope_tags": [base_tag],
        },
        {
            "id": "order_intake",
            "unit": "RMB m per tick",
            "distribution": {"type": "fixed", "value": book_value},
            "evidence_ref": "estimate: LABELED ASSUMPTION — opening new-orders flow = one year of intake at the intake-rate mode (same proxy as the stock)",
            "description": "期初年化新签订单流量（一年新签订单量的代理值，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "order_intake_rate",
            "unit": "annualized new orders / current revenue",
            "distribution": triangular(*intake_rate),
            "evidence_ref": "evidence: 2020 — new project orders ~RMB 7.0bn annualised (2020 annual-report summary, announcement 2021-010; decision-time INTERNAL figure) / FY2020 revenue RMB 6,799.06m ≈ 1.03x; 2015 — LABELED ASSUMPTION, no order-surge disclosure at end-2015, small book assumed",
            "description": "年化新签订单 / 当期收入（决策时点订单簿）",
            "scope_tags": [base_tag],
        },
        {
            "id": "backlog_conversion",
            "unit": "fraction of backlog converted per tick",
            "distribution": triangular(0.30, 0.40, 0.60),
            "evidence_ref": "estimate: LABELED ASSUMPTION — D2C (2026-11-25): the delivery schedule's on/off gate (min(1, backlog_conversion / 0.30) = 1 on the whole support, 0 when frozen off), not a per-tick rate; the lag evidence (design-in to start-of-production ~1-2 years) now calibrates the schedule, not this rate. Retained sampled so the sampling stream is unchanged.",
            "description": "订单簿通道开关（D2C：交付计划的门控，冻结时为 0）",
            "scope_tags": [base_tag],
        },
        {
            "id": "order_decay",
            "unit": "fraction of the order flow lost per tick",
            "distribution": triangular(0.10, 0.25, 0.40),
            "evidence_ref": "estimate: LABELED ASSUMPTION — per-tick decay of the new-orders flow (mean-reversion of order growth after a surge year)",
            "description": "新签订单流量的每 tick 衰减率（订单高峰过后均值回归）",
            "scope_tags": [base_tag],
        },
    ]


def _rd_wiring_variables(gross_base: float, gross_longrun: float,
                         rd_base: float, rd_longrun: float,
                         other_share: float, base_tag: str) -> list:
    """RD-path decomposition variables (EVIDENCE.md §2.2).

    Copied verbatim from rd-expense-path-2026-11-20/run_desay_gapb.py
    (the R&D-leg harness), including its evidence_refs. PROFIT
    MIGRATION NOTE (2026-11-23): on the current template (c61e302)
    these ids are TEMPLATE variables, so each entry here OVERRIDES the
    template value in place at merge — it does NOT append a new draw.
    The old harness comment "the ONLY new draw, LAST in the list"
    referred to the pre-promotion template, which carried no rd_adoption;
    on the current template rd_adoption already draws at the template's
    own position, and this entry restates its identical distribution.
    All eight entries are FIXED except rd_adoption, so the binding
    cannot shift the sampling stream: revenue/share draws are
    bit-identical to the merged-tip rerun.

    - gross_base / rd_base: FIXED decision-year point values
      (2015: gross 26.96% Tianfeng, rd 7.6% WEAK 2014 anchor;
      2020: gross 23.39%, rd 12.02%).
    - gross_longrun: FIXED mean-reversion anchor (2015: 25.5% WEAK,
      Wanlian 24-27% band midpoint — a two-year mean cannot be
      computed; 2020: (22.75+23.39)/2 = 23.07%).
    - rd_longrun: FIXED mean-reversion anchor (2015: 7.6% WEAK, same
      as base — single-point anchor, no reversion drift; 2020:
      (10.04+12.29)/2 = 11.17%).
    - other_share: FIXED t=1 residual (gross - rd - net), so the
      identity reproduces B's margin_base exactly at t=1
      (2015: 0.0958; 2020: 0.0375).
    - gross_reversion / rd_reversion: FIXED 0.25/tick — B's rate
      (round number, labeled assumption), shared by both terms.
    - rd_adoption: triangular(-0.02, 0.0, +0.02) — carries the adoption
      uncertainty B's margin_adoption used to carry (same ±0.02, mode 0,
      no double counting). margin_adoption itself is RETAINED, unread.
    FIREWALL: no 2025/2024 intensity, no 2016 R&D fee, no 2014-2017
    CAGR anywhere in these inputs.
    """
    return [
        {
            "id": "rd_longrun",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": rd_longrun},
            "evidence_ref": "estimate: LABELED ASSUMPTION — R&D-intensity mean-reversion anchor (2020: (10.04%+12.29%)/2=0.1117; 2015: 0.076 WEAK, same as base — single-point 2014 anchor, no reversion drift; EVIDENCE.md §1)",
            "description": "研发强度均值回归锚（标注假设；2015 WEAK）",
            "scope_tags": [base_tag],
        },
        {
            "id": "rd_base",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": rd_base},
            "evidence_ref": "evidence: 2020 — decision-year R&D intensity 12.02% (2020 annual-report summary); 2015 — 0.076 WEAK, 2014 anchor ≈¥200m / ¥2,636.69m (36Kr IPO report citing prospectus, second-hand, rounded to 100m; EVIDENCE.md §1.2)",
            "description": "研发强度基值（决策年；2015 WEAK）",
            "scope_tags": [base_tag],
        },
        {
            "id": "gross_longrun",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": gross_longrun},
            "evidence_ref": "estimate: LABELED ASSUMPTION — gross-margin mean-reversion anchor (2020: (22.75%+23.39%)/2=0.2307; 2015: 0.255 WEAK, Wanlian 24-27% band midpoint — two-year mean not computable; EVIDENCE.md §1)",
            "description": "毛利率均值回归锚（标注假设；2015 WEAK）",
            "scope_tags": [base_tag],
        },
        {
            "id": "gross_base",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": gross_base},
            "evidence_ref": "evidence: decision-year gross margin point value (2015: 26.96% Tianfeng; 2020: 23.39% Guojin/annual report; EVIDENCE.md §1)",
            "description": "毛利率基值（决策年点值）",
            "scope_tags": [base_tag],
        },
        {
            "id": "other_share",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": other_share},
            "evidence_ref": "estimate: LABELED ASSUMPTION — t=1 residual (gross - R&D - net) so the identity reproduces B's margin_base exactly at t=1 (2015: 0.2696-0.076-0.0978=0.0958; 2020: 0.2339-0.1202-0.0762=0.0375)",
            "description": "其他占比（毛利−研发−净利残差，固定）",
            "scope_tags": [base_tag],
        },
        {
            "id": "rd_reversion",
            "unit": "per-year",
            "distribution": {"type": "fixed", "value": 0.25},
            "evidence_ref": "estimate: LABELED ASSUMPTION — B's 0.25/tick reversion rate (round number), shared by both decomposition terms; no new free parameter",
            "description": "研发强度向长期均值回归的速度（每年收敛 1/4 偏离，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "gross_reversion",
            "unit": "per-year",
            "distribution": {"type": "fixed", "value": 0.25},
            "evidence_ref": "estimate: LABELED ASSUMPTION — B's 0.25/tick reversion rate (round number), shared by both decomposition terms; no new free parameter",
            "description": "毛利率向长期均值回归的速度（每年收敛 1/4 偏离，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "rd_adoption",
            "unit": "margin points per unit adoption",
            "distribution": triangular(-0.02, 0.0, 0.02),
            "evidence_ref": "estimate: LABELED ASSUMPTION — net effect of adoption on R&D intensity; mode 0 (no signed decision-time evidence); replaces margin_adoption's role (same ±0.02 band, no double counting)",
            "description": "每单位采用率对研发强度的净效应（众数 0，标注假设）",
            "scope_tags": [base_tag],
        },
    ]


# Auto-pack wiring appended to each case (same decision-time inputs as
# the corporate run, plus the pack wiring). The 2020 case uses the
# template's chain distributions as-is (they ARE the diagnostic spec);
# the 2015 case overrides the path outlook (see above).
CASES["desay-2015"]["variables"] += _autopack_wiring_variables(
    2459.76, (0.010, 0.0135, 0.018), "traditional",
    nev_path=((0.20, 0.30, 0.50), (0.40, 0.50, 0.70), (4.0, 5.0, 6.0)),
)
CASES["desay-2020"]["variables"] += _autopack_wiring_variables(
    2531.1, (0.045, 0.054, 0.065), "cockpit",
)
# Order-book wiring appended to each case (Track 11 §7): 2015 is the
# small-book control (intake mode 0.25x, book 917.06 = 0.25 x 3668.25);
# 2020 is the surging book (intake mode 1.00x, book 6799.06).
CASES["desay-2015"]["variables"] += _orderbook_wiring_variables(
    (0.15, 0.25, 0.40), 917.06, "traditional",
)
CASES["desay-2020"]["variables"] += _orderbook_wiring_variables(
    (0.80, 1.00, 1.20), 6799.06, "cockpit",
)
# ADAS wiring appended to each case (Track C1 §2): 2015 is the
# pre-L2 control (starting ~0, midpoint mode 5.0); 2020 is the
# L2-takeoff case (starting 12%, midpoint mode 3.0 from the template).
CASES["desay-2015"]["variables"] += _adas_wiring_variables(
    (0.00, 0.01, 0.02), (4.0, 5.0, 6.0), "traditional",
)
CASES["desay-2020"]["variables"] += _adas_wiring_variables(
    (0.11, 0.12, 0.16), None, "cockpit",
)
# R&D-leg wiring appended to each case (PROFIT MIGRATION 2026-11-23):
# binds the template's R&D decomposition legs to the decision-year
# figures (rd-expense-path EVIDENCE.md §2.2; same values the R&D
# harness used). Without this the template profit path would run on
# the template placeholder legs (gross 0.30 / rd 0.05 / other 0.05 ->
# net 0.20) instead of the case's product path.
CASES["desay-2015"]["variables"] += _rd_wiring_variables(
    0.2696, 0.255, 0.076, 0.076, 0.0958, "traditional",
)
CASES["desay-2020"]["variables"] += _rd_wiring_variables(
    0.2339, 0.2307, 0.1202, 0.1117, 0.0375, "cockpit",
)
# Arms pin the NEV coupling alongside the six growth levers (same
# values in both cases): A skeptical (min), B plan-optimistic (mode),
# C middle. The fitted values that would reach the actuals (2.08 /
# 9.69 planning path) are NEVER pinned.
for _case in CASES.values():
    for _arm, _k, _ks in zip(_case["arms"], (0.10, 0.25, 0.15), (0.10, 0.20, 0.15)):
        _arm["overrides"]["nev_coupling"] = _k
        _arm["overrides"]["adas_coupling"] = _k
        _arm["overrides"]["adas_share_coupling"] = _ks
# A-TIER (Ho 2026-11-22 20:30): the B arm takes the PRE-REGISTERED
# skeptic ADAS values (adas_coupling 0.10 / adas_share_coupling 0.10)
# instead of the plan-optimistic B values (0.25 / 0.20). nev_coupling
# is untouched (B stays 0.25); A and C arms keep their pinned values.
# Nothing else in this file changes for the A-tier rerun.
for _case in CASES.values():
    _b = next(a for a in _case["arms"] if a["name"].startswith("B "))
    _b["overrides"]["adas_coupling"] = 0.10
    _b["overrides"]["adas_share_coupling"] = 0.10


# Arms that history realized (scoring only; same as REPORT.md).
REALIZED = {
    "desay-2015": "B invest smart cockpit ADAS",
    "desay-2020": "B aggressive intelligent driving push",
}


def run_case(name: str, spec: dict, skip_derive: bool = False) -> dict:
    out: dict = {"case": name, "steps": {}}
    print(f"\n===== CASE {name} =====", flush=True)

    # 1. MECE validate
    st, body = call("POST", "/mece/validate", spec["decomposition"])
    save(name, "01-mece-validate", st, body)
    out["steps"]["mece_validate"] = {"http": st, "is_mece": body.get("is_mece") if isinstance(body, dict) else None}
    print(f"  mece/validate -> {st} is_mece={out['steps']['mece_validate']['is_mece']}", flush=True)
    if st != 200:
        out["error"] = "mece validate failed"
        return out

    # 2. Anchor run (auto pack: builtin template merged with the case set)
    payload = {
        "company_id": spec["company_id"],
        "company_name": spec["company_name"],
        "market": spec["market"],
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 5,
        "seed": 7,
        "decision_time": spec["decision_time"],
        "decomposition": spec["decomposition"],
        "variable_template_id": "builtin:automotive",
        "variable_set": {
            "name": f"{name}-case",
            "variables": spec["variables"],
            "formulas": spec["formulas"],
            "internal": spec["internal"],
        },
    }
    st, body = call("POST", "/simulation/runs", payload)
    save(name, "02-anchor-run", st, body)
    if st != 201 or not isinstance(body, dict) or "id" not in body:
        out["error"] = f"anchor run failed http={st}"
        print(f"  anchor run FAILED http={st}: {str(body)[:400]}", flush=True)
        return out
    anchor_id = body["id"]
    out["anchor_run_id"] = anchor_id
    out["steps"]["anchor"] = {"http": st, "status": body.get("status"), "tick_count": body.get("tick_count")}
    print(f"  anchor run {anchor_id} status={body.get('status')}", flush=True)

    # 3. Anchor ensemble, share
    st, body = call("POST", f"/runs/{anchor_id}/monte-carlo",
                    {"trials": 50, "seed": 42, "metric": "market_share",
                     "loss_threshold": spec["loss_threshold"]})
    save(name, "03-anchor-monte-carlo", st, body)
    if st != 201:
        out["error"] = f"anchor monte-carlo failed http={st}"
        print(f"  anchor monte-carlo FAILED http={st}", flush=True)
        return out
    out["anchor_ensemble"] = body
    b = body["baseline"]
    print(f"  anchor ensemble: P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']}", flush=True)

    # 3b. Anchor ensemble, revenue metric
    st, body = call("POST", f"/runs/{anchor_id}/monte-carlo",
                    {"trials": 50, "seed": 42, "metric": "revenue",
                     "loss_threshold": spec["revenue_loss_threshold"]})
    save(name, "03b-anchor-monte-carlo-revenue", st, body)
    if st != 201:
        out["error"] = f"anchor revenue monte-carlo failed http={st}"
        print(f"  anchor revenue monte-carlo FAILED http={st}: {str(body)[:400]}", flush=True)
        return out
    out["anchor_ensemble_revenue"] = body
    b = body["baseline"]
    print(f"  anchor ensemble revenue: P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']}", flush=True)

    # 4. Anchor expected shortfall (lower tail, alpha 0.05)
    st, body = call("POST", f"/runs/{anchor_id}/robustness/expected-shortfall",
                    {"alpha": 0.05, "tail": "lower"})
    save(name, "04-anchor-expected-shortfall", st, body)
    out["steps"]["anchor_es"] = {"http": st}
    print(f"  anchor ES -> {st}", flush=True)

    # 5. Override branches (one request, all arms; fork_step=1 = decide at time zero)
    dirs = []
    for arm in spec["arms"]:
        d = dict(arm)
        d["fork_step"] = 1
        dirs.append(d)
    st, body = call("POST", f"/runs/{anchor_id}/directions/override", {"directions": dirs})
    save(name, "05-override", st, body)
    if st != 201:
        out["error"] = f"override failed http={st}"
        print(f"  override FAILED http={st}: {str(body)[:400]}", flush=True)
        return out
    out["override"] = body
    children = {}
    for outcome in body.get("outcomes", []):
        print(f"  override {outcome.get('name')}: {outcome.get('outcome')} child={outcome.get('child_run_id')}", flush=True)
        if outcome.get("child_run_id"):
            children[outcome["name"]] = outcome["child_run_id"]
    out["child_run_ids"] = children

    # 6. Ensemble + ES per child
    out["child_ensembles"] = {}
    out["child_ensembles_revenue"] = {}
    for arm_name, child_id in children.items():
        st, body = call("POST", f"/runs/{child_id}/monte-carlo",
                        {"trials": 50, "seed": 42, "metric": "market_share",
                         "loss_threshold": spec["loss_threshold"]})
        tag = "".join(c if (c.isalnum() or c in "-_") else "_" for c in arm_name.replace(" ", "_"))
        save(name, f"06-mc-{tag}", st, body)
        if st != 201:
            out.setdefault("errors", []).append(f"child mc failed {arm_name} http={st}")
            print(f"  child mc {arm_name} FAILED http={st}", flush=True)
            continue
        out["child_ensembles"][arm_name] = body
        b = body["baseline"]
        print(f"  child {arm_name}: P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']}", flush=True)
        # 6b. Child ensemble, revenue metric
        st, body = call("POST", f"/runs/{child_id}/monte-carlo",
                        {"trials": 50, "seed": 42, "metric": "revenue",
                         "loss_threshold": spec["revenue_loss_threshold"]})
        save(name, f"06b-mc-revenue-{tag}", st, body)
        if st != 201:
            out.setdefault("errors", []).append(f"child revenue mc failed {arm_name} http={st}")
            print(f"  child revenue mc {arm_name} FAILED http={st}: {str(body)[:300]}", flush=True)
        else:
            out["child_ensembles_revenue"][arm_name] = body
            b = body["baseline"]
            print(f"  child revenue {arm_name}: P50={b['p50']} P10={b['p10']} P90={b['p90']} p_loss={b['p_loss']}", flush=True)
        st2, body2 = call("POST", f"/runs/{child_id}/robustness/expected-shortfall",
                          {"alpha": 0.05, "tail": "lower"})
        save(name, f"07-es-{tag}", st2, body2)
        print(f"  child ES {arm_name} -> {st2}", flush=True)
        st3, body3 = call("GET", f"/runs/{child_id}")
        save(name, f"08-child-run-{tag}", st3, body3)
        st4, body4 = call("GET", f"/runs/{child_id}/replay-package")
        save(name, f"09-child-replay-{tag}", st4, body4)

    # 7. Anchor replay package (deterministic trajectory)
    st, body = call("GET", f"/runs/{anchor_id}/replay-package")
    save(name, "10-anchor-replay", st, body)

    # 8. Derive
    if not skip_derive:
        st, body = call("POST", f"/runs/{anchor_id}/directions/derive", {})
        save(name, "11-derive", st, body)
        out["derive"] = body
        if isinstance(body, dict):
            for oc in body.get("outcomes", []):
                print(f"  derive {oc.get('rule_id')}: {oc.get('status')} -> {oc.get('direction_name')} "
                      f"run={str(oc.get('source_run_id'))[:8]} arm={oc.get('arm')} p50={oc.get('p50')} p_loss={oc.get('p_loss')}", flush=True)

    # 9. Frozen-baseline decomposition (diagnostic Appendix A, per
    # channel): B with backlog_conversion=0 and EVERY other variable
    # pinned at B's sampled values, so the replay difference to B is
    # the BACKLOG channel's marginal contribution alone (the NEV chain
    # stays on in both). Runs AFTER derive so it is not a direction
    # candidate. Its MC would be degenerate (nothing left to resample),
    # so only the replay is taken.
    try:
        realized = REALIZED[name]
        b_arm = next(a for a in spec["arms"] if a["name"] == realized)
        b_child_id = out.get("child_run_ids", {}).get(realized)
        # The B child's sampled values live in the determinism endpoint
        # (run summary fragment), not in the replay package.
        sampled = {}
        if b_child_id:
            st_det, body_det = call("GET", f"/runs/{b_child_id}/determinism")
            if st_det == 200 and isinstance(body_det, dict):
                sampled = dict(body_det.get("sampled_values") or {})
        if sampled:
            frozen_overrides = dict(sampled)
            frozen_overrides["backlog_conversion"] = 0.0
            b_arm = next(a for a in spec["arms"] if a["name"] == realized)
            frozen_dir = {
                "name": "B frozen no-backlog",
                "overrides": frozen_overrides,
                "arm": "baseline",
                "mece_branches": b_arm["mece_branches"],
                "resample_variables": True,
                "fork_step": 1,
            }
            st, body = call("POST", f"/runs/{anchor_id}/directions/override",
                            {"directions": [frozen_dir]})
            save(name, "12-frozen-override", st, body)
            if st == 201 and isinstance(body, dict) and body.get("outcomes"):
                frozen_child = body["outcomes"][0].get("child_run_id")
                out["frozen_child_run_id"] = frozen_child
                print(f"  frozen no-backlog child {str(frozen_child)[:8]}", flush=True)
                if frozen_child:
                    st2, body2 = call("GET", f"/runs/{frozen_child}/replay-package")
                    save(name, "13-frozen-replay", st2, body2)
                    print(f"  frozen replay -> {st2}", flush=True)
            else:
                out.setdefault("errors", []).append(f"frozen override failed http={st}")
                print(f"  frozen override FAILED http={st}: {str(body)[:300]}", flush=True)
        else:
            out.setdefault("errors", []).append("frozen decomposition skipped: no sampled_values in B replay")
            print("  frozen decomposition SKIPPED (no sampled_values)", flush=True)
    except Exception as exc:  # noqa: BLE001 — decomposition is supplementary; never fail the run
        out.setdefault("errors", []).append(f"frozen decomposition error: {exc}")
        print(f"  frozen decomposition ERROR: {exc}", flush=True)

    # 9b. Frozen-baseline ADAS decomposition (Track C1, same method):
    # B with adas_coupling=0 AND adas_share_coupling=0 and EVERY other
    # variable pinned at B's sampled values, so the replay difference
    # to B is the ADAS channel's marginal contribution alone (the NEV
    # chain and the backlog stay on in both). Runs AFTER derive so it
    # is not a direction candidate. Its MC would be degenerate, so
    # only the replay is taken.
    try:
        realized = REALIZED[name]
        b_arm = next(a for a in spec["arms"] if a["name"] == realized)
        b_child_id = out.get("child_run_ids", {}).get(realized)
        sampled = {}
        if b_child_id:
            st_det, body_det = call("GET", f"/runs/{b_child_id}/determinism")
            if st_det == 200 and isinstance(body_det, dict):
                sampled = dict(body_det.get("sampled_values") or {})
        if sampled:
            frozen_overrides = dict(sampled)
            frozen_overrides["adas_coupling"] = 0.0
            frozen_overrides["adas_share_coupling"] = 0.0
            frozen_dir = {
                "name": "B frozen no-adas",
                "overrides": frozen_overrides,
                "arm": "baseline",
                "mece_branches": b_arm["mece_branches"],
                "resample_variables": True,
                "fork_step": 1,
            }
            st, body = call("POST", f"/runs/{anchor_id}/directions/override",
                            {"directions": [frozen_dir]})
            save(name, "12b-frozen-adas-override", st, body)
            if st == 201 and isinstance(body, dict) and body.get("outcomes"):
                frozen_child = body["outcomes"][0].get("child_run_id")
                out["frozen_adas_child_run_id"] = frozen_child
                print(f"  frozen no-adas child {str(frozen_child)[:8]}", flush=True)
                if frozen_child:
                    st2, body2 = call("GET", f"/runs/{frozen_child}/replay-package")
                    save(name, "13b-frozen-adas-replay", st2, body2)
                    print(f"  frozen adas replay -> {st2}", flush=True)
            else:
                out.setdefault("errors", []).append(f"frozen adas override failed http={st}")
                print(f"  frozen adas override FAILED http={st}: {str(body)[:300]}", flush=True)
        else:
            out.setdefault("errors", []).append("frozen adas decomposition skipped: no sampled_values in B replay")
            print("  frozen adas decomposition SKIPPED (no sampled_values)", flush=True)
    except Exception as exc:  # noqa: BLE001 — decomposition is supplementary; never fail the run
        out.setdefault("errors", []).append(f"frozen adas decomposition error: {exc}")
        print(f"  frozen adas decomposition ERROR: {exc}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=list(CASES) + ["all"], default="all")
    ap.add_argument("--skip-derive", action="store_true")
    args = ap.parse_args()
    names = list(CASES) if args.case == "all" else [args.case]
    summary = {}
    for name in names:
        summary[name] = run_case(name, CASES[name], skip_derive=args.skip_derive)
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("\nDONE. summary -> raw/summary.json", flush=True)


if __name__ == "__main__":
    main()
