#!/usr/bin/env python3
"""Classic-case backtests on merged mainline e047f50: Huawei 2000 / Nokia 2007.
Blockbuster 2000 runs as a PARTIAL case (branch fix/blockbuster-partial-case,
2026-11-26; Ho 2026-11-24: direction + magnitude + revenue milestone,
profit NOT built — 1999 net margin -1.55%, below the product profit
chain's [0.02, 0.25] clamp, so no profit variable and no margin wiring;
the corporate template's default profit state field is computed by the
backend but is NEVER scored or cited for this case). Copied from
run_backtests_rerun.py; only BASE/OUT/case-list changed.)

PROFIT MIGRATION (2026-11-23, Ho 11:05 order): the case-level decoupled
profit drivers are REMOVED (Huawei's profit_driver(); Nokia's
diffusion_drivers(with_profit=True) -> with_profit=False) and the runs
now read the corporate template's product profit path (profit = revenue
x net_margin, single-regression margin chain), with margin_base /
margin_longrun bound per case via _margin_wiring_variables() below
(values + evidence copied verbatim from the profit-chain-pack rerun,
profit-chain-pack-2026-11-20/rerun/run_classic_profit_pack.py).
REQUIRED companion change: the anchor payload now carries
variable_template_id "builtin:corporate". The backend merges a template
ONLY when that id is set (engine.py _resolve_variable_bindings); without
it the corporate template was never merged in the e047f50 / merged-tip
reruns, and removing the case profit driver would have left profit
driverless. Attaching the template PREPENDS two sampled draws
(margin_base, margin_adoption) ahead of the case variables, so the
classic sampling stream SHIFTS vs the merged rerun — revenue/share
ensembles will move (unlike Desay, whose template was already merged).
That shift is inherent to the migration, not a regression; it is the
same shift the profit-chain-pack rerun accepted and re-baselined.
profit_growth variables and the arms' profit overrides are retained
(sampled but unread) so the case-variable order itself is unchanged.

Runs each case through the local MingJian-fork backend (SQLite dev path):
  anchor run (MECE tree + variable table + tick-driver formula + decision_time)
  -> Monte Carlo ensemble (trials=50, seed=42, metric=market_share)
  -> expected shortfall (alpha=0.05, lower tail)
  -> override branches, one per candidate direction (fork_step=1)
  -> ensemble + expected shortfall per branch
  -> rule-path derivation over the scenario family
  -> per-tick trajectory extraction (ticks 0/5/10) from trial-run snapshots

Backend: scratch uvicorn (BACKTEST_BASE, default :8024), own DB $BACKTEST_RUN_DIR/trials50-fbook.db.
Hub was unreachable (SSH hangs since ~10:58 CST 2026-11-19); see REPORT.md.

Modeling conventions (labeled, see REPORT.md for the full audit):
- domain=corporate, actor_template=ai_model_provider, tick_count=10,
  1 tick = 1 year (labeled convention; the corporate pack has no calendar).
- Metric: market_share (a corporate state field). Loss = final share below
  the decision-point starting mode.
- Dynamics: ONE tick-driver formula per case:
    market_share = min(0.85, market_share * (1 + share_growth))
  share_growth is sampled once per run (anchor) or fixed per arm (override).
  No claims are ingested, so no keyword rules fire; trajectories are driven
  purely by the sampled/fixed growth rate. The driver formula IS the case's
  causal model, and its coefficients are labeled assumptions.
- Arm growth rates are set from DECISION-POINT reasoning only, never tuned
  to the actual outcome. Sensitivity is reported in REPORT.md.

Usage: python3 run_classic.py [--case huawei|nokia|blockbuster|all] [--skip-derive]
Writes raw JSON per step to raw/<case>/ and a summary to summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

import backtest_common  # repo root on sys.path, shared config

BASE = backtest_common.get_base()
OUT = str(backtest_common.get_run_dir() / "raw-classic")
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


def growth_driver():
    return {
        "output": "market_share",
        "expression": {
            "op": "min",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "market_share"},
                        {"op": "add", "args": [1, {"ref": "share_growth"}]},
                    ],
                },
                0.85,
            ],
        },
        "description": "Share compounds annually at share_growth; capped at 0.85 (labeled assumption).",
        "tick_driver": True,
    }


def revenue_driver():
    return {
        "output": "revenue",
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "revenue"},
                {"op": "add", "args": [1, {"ref": "revenue_growth"}]},
            ],
        },
        "description": "Revenue compounds annually at revenue_growth (no disruption coupling: growth case).",
        "tick_driver": True,
    }


def diffusion_drivers(with_profit: bool):
    """Logistic S-curve disruption drivers (Fix 2, canonical recipe).

    adoption = logistic(rate * (tick - midpoint), ceiling)
    share   = max(0, share * (1 + base_growth - coupling * adoption))
    revenue = max(0, revenue * (1 + revenue_growth - coupling * adoption))
    profit  = max(0, profit * (1 + profit_growth - coupling * adoption))  [if with_profit]
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
        "description": "Disruptor adoption S-curve (logistic in tick); within-tick intermediate, not a state field.",
        "tick_driver": True,
    }

    def _coupled(field: str, growth: str) -> dict:
        return {
            "output": field,
            "expression": {
                "op": "max",
                "args": [
                    0,
                    {
                        "op": "multiply",
                        "args": [
                            {"ref": field},
                            {
                                "op": "add",
                                "args": [
                                    1,
                                    {
                                        "op": "subtract",
                                        "args": [
                                            {"ref": growth},
                                            {
                                                "op": "multiply",
                                                "args": [{"ref": "disruptor_coupling"}, {"ref": "disruptor_adoption"}],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            "description": f"{field} grows at {growth} minus coupling * disruptor adoption; floored at 0.",
            "tick_driver": True,
        }

    drivers = [adoption, _coupled("market_share", "base_growth"), _coupled("revenue", "revenue_growth")]
    if with_profit:
        drivers.append(_coupled("profit", "profit_growth"))
    return drivers


CASES = {
    "huawei": {
        "company_id": "backtest-huawei-2000",
        "company_name": "Huawei (2000 retrospective)",
        "market": "telecom-equipment",
        "decision_time": "2000-12-31T00:00:00Z",
        "loss_threshold": 0.03,
        "revenue_loss_threshold": 220,
        "formulas": [growth_driver(), revenue_driver()],
        "topic": "华为2000：冬天来了，收缩过冬还是坚持投入？",
        "decomposition": {
            "topic": "华为2000：冬天来了，收缩过冬还是坚持投入？",
            "root": {
                "name": "华为2000：冬天来了，怎么过冬",
                "scope": ["growth", "survival"],
                "children": [
                    {"name": "增长", "scope": ["growth"]},
                    {"name": "生存", "scope": ["survival"]},
                ],
            },
        },
        "variables": [
            {
                "id": "market_share",
                "unit": "share",
                "distribution": triangular(0.02, 0.03, 0.05),
                "evidence_ref": "estimate: labeled assumption — 2000 global share not publicly disclosed; 2000 contract sales $2.65B",
                "description": "2000年全球电信设备市场份额（起始值）",
                "scope_tags": ["growth"],
            },
            {
                "id": "share_growth",
                "unit": "per-year",
                "distribution": triangular(-0.05, 0.08, 0.25),
                "evidence_ref": "estimate: 1995-2000 sales grew ~70%/yr (RMB 1.5B→22B); Dec 2000 bubble burst + winter warning; wide distribution, mode 8%",
                "description": "年均份额增长率（锚定run的不确定性范围）",
                "scope_tags": ["growth"],
            },
            {
                "id": "revenue",
                "unit": "RMB 100M",
                "distribution": triangular(180, 220, 260),
                "evidence_ref": "evidence: 2000 sales RMB 22B (220亿), profit RMB 2.9B; decision-time internal figure",
                "description": "年销售收入，单位亿人民币（起始值）",
                "scope_tags": ["growth"],
            },
            {
                "id": "revenue_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.15, 0.35),
                "evidence_ref": "estimate: 1995-2000 sales ~70%/yr, bubble burst moderates; own targets 2001 400亿 (+82%) / 2002 600亿 (+50%) show high ambition, mode 15% conservative",
                "description": "年均收入增长率（锚定run的不确定性范围）",
                "scope_tags": ["growth"],
            },
            {
                "id": "profit",
                "unit": "RMB 100M",
                "distribution": triangular(24, 29, 35),
                "evidence_ref": "evidence: 2000 profit RMB 2.9B (29亿)",
                "description": "年利润，单位亿人民币（起始值）",
                "scope_tags": ["growth"],
            },
            {
                "id": "profit_growth",
                "unit": "per-year",
                "distribution": triangular(0.0, 0.12, 0.30),
                "evidence_ref": "estimate: labeled assumption, tracks revenue growth at a lower mode (margin pressure in a downturn)",
                "description": "年均利润增长率（锚定run的不确定性范围）",
                "scope_tags": ["growth"],
            },
        ],
        "internal": {
            "decision_point": "2000-12-31, 任正非《华为的冬天》",
            "sales_2000": "220亿人民币，利润29亿，中国电子百强第一",
            "overseas_2000": "海外合同销售额仅1亿多美元，1999年海外收入<4%",
            "context": "互联网泡沫破裂，全球IT投资下滑；2000年引入IBM ISC；10月校招10000人",
        },
        "arms": [
            {"name": "A 收缩保利润", "overrides": {"share_growth": 0.0, "revenue_growth": 0.05, "profit_growth": 0.05}, "arm": "baseline", "mece_branches": ["生存"], "resample_variables": True},
            {"name": "B 坚持投入", "overrides": {"share_growth": 0.15, "revenue_growth": 0.22, "profit_growth": 0.18}, "arm": "baseline", "mece_branches": ["增长"], "resample_variables": True},
            {"name": "C 聚焦国内", "overrides": {"share_growth": 0.05, "revenue_growth": 0.12, "profit_growth": 0.10}, "arm": "baseline", "mece_branches": ["增长"], "resample_variables": True},
        ],
    },
    "nokia": {
        "company_id": "backtest-nokia-2007",
        "company_name": "Nokia (2007 retrospective)",
        "market": "mobile-phones",
        "decision_time": "2007-06-29T00:00:00Z",
        "loss_threshold": 0.41,
        "revenue_loss_threshold": 41.1,
        "formulas": diffusion_drivers(with_profit=False),
        "topic": "诺基亚2007：iPhone来了，坚持Symbian还是转向全触屏生态？",
        "decomposition": {
            "topic": "诺基亚2007：iPhone来了，坚持Symbian还是转向全触屏生态？",
            "root": {
                "name": "诺基亚2007：iPhone来了，怎么选",
                "scope": ["ecosystem", "hardware"],
                "children": [
                    {"name": "生态", "scope": ["ecosystem"]},
                    {"name": "硬件", "scope": ["hardware"]},
                ],
            },
        },
        "variables": [
            {
                "id": "market_share",
                "unit": "share",
                "distribution": triangular(0.38, 0.41, 0.44),
                "evidence_ref": "evidence: 2007年诺基亚全球手机份额超40%",
                "description": "2007年全球手机市场份额（起始值）",
                "scope_tags": ["hardware"],
            },
            {
                "id": "base_growth",
                "unit": "per-year",
                "distribution": triangular(-0.03, 0.01, 0.04),
                "evidence_ref": "estimate: 2002-2007 share rose slowly, mode +1%; underlying growth absent disruption (same mode as first-run share_growth)",
                "description": "无颠覆时的年均份额增长率",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "disruptor_ceiling",
                "unit": "share",
                "distribution": triangular(0.7, 0.9, 0.95),
                "evidence_ref": "estimate: LABELED ASSUMPTION (canonical recipe value) — touchscreen smartphones eventually saturate ~90% of the handset market; no 2007 analyst S-curve in inputs",
                "description": "颠覆者（触屏智能机）采用率饱和水平 K",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "disruptor_rate",
                "unit": "per-year",
                "distribution": triangular(0.8, 1.2, 1.6),
                "evidence_ref": "estimate: LABELED ASSUMPTION (canonical recipe value) — logistic steepness; iPhone just launched Jun 2007, adoption speed genuinely uncertain at decision time",
                "description": "颠覆者采用 logistic 曲线陡峭度 r",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "disruptor_midpoint",
                "unit": "years",
                "distribution": triangular(2.0, 3.0, 4.0),
                "evidence_ref": "estimate: LABELED ASSUMPTION (canonical recipe value) — adoption passes K/2 ~3 years out (2010); reasoning: new category from ~0 in Jun 2007, carrier/price friction; range 2-4y",
                "description": "颠覆者采用率过半的时点（tick）",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "disruptor_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.4, 0.55, 0.7),
                "evidence_ref": "estimate: LABELED ASSUMPTION (canonical recipe value) — each unit of touchscreen adoption destroys ~0.55 units of incumbent share growth per tick (1:1 substitution in the same purchase, partly offset by brand/channel)",
                "description": "每单位颠覆者采用率对既有份额增长的侵蚀系数",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "revenue",
                "unit": "EUR B",
                "distribution": triangular(36, 41.1, 48),
                "evidence_ref": "evidence: 2006 net sales EUR 41.1B (reported Jan 2007, decision-time known); 2007 full-year EUR 51.1B was NOT known on 2007-06-29 and is not used as input",
                "description": "年净销售额，单位十亿欧元（起始值，2006年为基准）",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "revenue_growth",
                "unit": "per-year",
                "distribution": triangular(-0.05, 0.10, 0.25),
                "evidence_ref": "estimate: 2006 net sales +20% vs 2005 (EUR 34.2B); mode +10% conservative after the iPhone launch",
                "description": "无颠覆时的年均收入增长率",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "profit",
                "unit": "EUR B",
                "distribution": triangular(4.5, 5.5, 6.5),
                "evidence_ref": "evidence: 2006 operating profit EUR 5.5B (5,488M, reported Jan 2007)",
                "description": "年营业利润，单位十亿欧元（起始值）",
                "scope_tags": ["ecosystem"],
            },
            {
                "id": "profit_growth",
                "unit": "per-year",
                "distribution": triangular(-0.05, 0.08, 0.20),
                "evidence_ref": "estimate: labeled assumption, tracks revenue growth at a lower mode",
                "description": "无颠覆时的年均利润增长率",
                "scope_tags": ["ecosystem"],
            },
        ],
        "internal": {
            "decision_point": "2007-06-29, iPhone发布",
            "share_2007": "全球手机份额超40%，全球第一；N95被誉为功能机巅峰",
            "symbian": "Symbian智能机自2002年（7650）起已成体系",
            "context": "iPhone被诺基亚视为小众产品；Android尚未发布（2007年11月）",
        },
        "arms": [
            {"name": "A 坚持Symbian", "overrides": {"base_growth": 0.01, "disruptor_coupling": 0.55, "revenue_growth": 0.10, "profit_growth": 0.08}, "arm": "baseline", "mece_branches": ["生态"], "resample_variables": True},
            {"name": "B 转向触屏生态", "overrides": {"base_growth": 0.02, "disruptor_coupling": 0.20, "revenue_growth": 0.12, "profit_growth": 0.10}, "arm": "baseline", "mece_branches": ["生态"], "resample_variables": True},
        ],
    },
    "blockbuster": {
        # PARTIAL CASE (Ho 2026-11-24; built 2026-11-26, branch
        # fix/blockbuster-partial-case): direction + magnitude + revenue
        # milestone only. PROFIT NOT BUILT: no profit variable, no margin
        # wiring — 1999 net margin is -1.55% (net loss $69.2M on revenues
        # $4,463.5M, 1999 10-K), and the pre-decision two-year mean is
        # also negative (1998 net loss $336.6M), so margin_base AND
        # margin_longrun would both fall below the corporate profit
        # chain's [0.02, 0.25] clamp (template_spec.py) and the chain
        # would pin profit at revenue x 2% by construction. The
        # template's default profit state field is computed by the
        # backend but is never scored or cited for this case. The
        # $50M Netflix anecdote is DISPUTED (Antioco denied a formal
        # acquisition discussion) and is never used as a case input.
        # S1+S2 FIX (Ho 2026-11-26 13:29; branch fix/blockbuster-2003-s1s2):
        # S1 re-anchors the revenue start level from the 1999 print to the
        # 2000 H1 annualized run-rate (Q2 2000 10-Q, filed 2000-08-14, 18
        # days before the decision point); S2 halves this case's downside
        # occurrence (0.5 -> 0.25) on the 1990-91 recession record for
        # video rental. Both changes use decision-time evidence only;
        # the global downside defaults are untouched (C2 stays
        # non-compliant). See the revenue variable, the downturn_occurs
        # variable, and revenue_loss_threshold below.
        "company_id": "backtest-blockbuster-2000",
        "company_name": "Blockbuster (2000 retrospective)",
        "market": "video-rental",
        "decision_time": "2000-09-01T00:00:00Z",
        "loss_threshold": 0.36,
        "revenue_loss_threshold": 4.85,
        "formulas": diffusion_drivers(with_profit=False),
        "topic": "Blockbuster 2000：收购/合作Netflix还是坚持门店模式？",
        "decomposition": {
            "topic": "Blockbuster 2000：收购/合作Netflix还是坚持门店模式？",
            "root": {
                "name": "Blockbuster 2000：Netflix来了，怎么选",
                "scope": ["stores", "channels"],
                "children": [
                    {"name": "门店", "scope": ["stores"]},
                    {"name": "渠道", "scope": ["channels"]},
                ],
            },
        },
        "variables": [
            {
                "id": "market_share",
                "unit": "share",
                "distribution": triangular(0.32, 0.36, 0.40),
                "evidence_ref": "evidence: Blockbuster 2000年报，美国租赁市场份额36%（1999年约30%）",
                "description": "2000年美国视频租赁市场份额（起始值）",
                "scope_tags": ["stores"],
            },
            {
                "id": "base_growth",
                "unit": "per-year",
                "distribution": triangular(-0.05, 0.02, 0.06),
                "evidence_ref": "estimate: 2000 share 32%→36% rising, mode +2%; underlying growth absent disruption (same mode as first-run share_growth)",
                "description": "无颠覆时的年均份额增长率",
                "scope_tags": ["channels"],
            },
            {
                "id": "disruptor_ceiling",
                "unit": "share",
                "distribution": triangular(0.7, 0.9, 0.95),
                "evidence_ref": "estimate: LABELED ASSUMPTION — mail-DVD subscription + streaming eventually saturate ~90% of home-video rental; no 2000 analyst S-curve in inputs",
                "description": "颠覆者（邮寄订阅/流媒体）采用率饱和水平 K",
                "scope_tags": ["channels"],
            },
            {
                "id": "disruptor_rate",
                "unit": "per-year",
                "distribution": triangular(0.8, 1.0, 1.2),
                "evidence_ref": "estimate: LABELED ASSUMPTION — slower than smartphones: 2000 broadband users few, streaming substitution early; rate mode 1.0 vs Nokia 1.2",
                "description": "颠覆者采用 logistic 曲线陡峭度 r",
                "scope_tags": ["channels"],
            },
            {
                "id": "disruptor_midpoint",
                "unit": "years",
                "distribution": triangular(5.0, 6.0, 7.0),
                "evidence_ref": "estimate: LABELED ASSUMPTION — adoption passes K/2 ~6 years out (2006); reasoning: Sep 2000 Netflix ~120k subscribers, broadband scarce, mail-DVD + streaming need years of infrastructure buildout; deliberately later than Nokia (3y) because the substitute was further away",
                "description": "颠覆者采用率过半的时点（tick）",
                "scope_tags": ["channels"],
            },
            {
                "id": "disruptor_coupling",
                "unit": "per-unit-adoption",
                "distribution": triangular(0.4, 0.55, 0.7),
                "evidence_ref": "estimate: LABELED ASSUMPTION — each unit of mail/streaming adoption destroys ~0.55 units of incumbent share growth per tick (same substitution logic as Nokia)",
                "description": "每单位颠覆者采用率对既有份额增长的侵蚀系数",
                "scope_tags": ["channels"],
            },
            {
                "id": "revenue",
                "unit": "USD B",
                # S1 (fix/blockbuster-2003-s1s2, Ho 2026-11-26 13:29): the
                # start level is re-anchored from the 1999 print (4.46) to
                # the 2000 H1 annualized run-rate. Q2 2000 10-Q (SEC, filed
                # 2000-08-14, 18 days before the 2000-09-01 decision point):
                # H1 revenue $2,425.5M, +12.6% YoY, Q2 alone +16.5% ->
                # annualized $4.851B. Shift +0.39 (= 4.85 - 4.46) applied
                # to all three parameters, spread preserved (width 0.70,
                # mode 0.26 above min, as before). The 2000 full-year
                # $4.96B was NOT known on 2000-09-01 and is not used.
                "distribution": triangular(4.59, 4.85, 5.29),
                "evidence_ref": "evidence: 2000 H1 revenue $2,425.5M (+12.6% YoY, Q2 +16.5%), Q2 2000 10-Q filed 2000-08-14, decision-time known; annualized $4.851B; whole distribution re-anchored +0.39 from the 1999 print $4.46B (1999 10-K), spread preserved",
                "description": "年总收入，单位十亿美元（起始值，2000 年上半年年化 run-rate 为基准）",
                "scope_tags": ["channels"],
            },
            {
                "id": "revenue_growth",
                "unit": "per-year",
                "distribution": triangular(-0.05, 0.06, 0.15),
                "evidence_ref": "estimate: labeled assumption — store growth + late fees, moderating; 1999-2004 revenue CAGR 6.3% is post-decision and not used",
                "description": "无颠覆时的年均收入增长率",
                "scope_tags": ["channels"],
            },
            {
                # S2 (fix/blockbuster-2003-s1s2, Ho 2026-11-26 13:29):
                # this case binds its own downturn_occurs, so the engine
                # keeps this definition and fills only the other four
                # downside variables from the unified default (downside.py:
                # a caller-bound id is never overwritten). Occurrence
                # 0.5 -> 0.25, CASE-ONLY: the global default is untouched
                # (C2 — unifying the parameter across cases — stays
                # non-compliant). Depth / start / duration / persistent
                # stay at the unified default; no independent estimate is
                # claimed for a new depth. Appended at the END of the case
                # variables so the pre-existing draws are untouched; only
                # the four default-filled downside draws shift by one
                # position in the sampling stream.
                "id": "downturn_occurs",
                "unit": "probability",
                "distribution": {"type": "bernoulli", "p": 0.25},
                "evidence_ref": "estimate: CASE DOWNGRADE (S2) — default 0.5 halved to 0.25 for video rental: 1990-91 recession (NBER Jul 1990-Mar 1991) did not dent rental demand — BLS industry output (NAICS 532282) rose nominally 1990 $5,006.9M -> 1991 $5,035.9M (+0.6%), real dip only -3.2% for one year; worst observed hit ~1/6 of default modal depth 0.20. Full chain in blockbuster-2003-fix-2026-11-26/REPORT.md",
                "description": "本案周期下行发生概率（租赁抗周期，默认 0.5 降档至 0.25）",
                "scope_tags": [],
            },
        ],
        "internal": {
            "decision_point": "2000-09-01, Netflix管理层到访达拉斯总部",
            "share_2000": "美国租赁市场份额36%，9000+门店（全球），1999年收入44.6亿美元",
            "netflix_2000": "邮寄DVD订阅小公司，12万用户量级，当年预计亏损500万美元",
            "context": "盈利依赖门店租金与逾期费；2000年宽带用户尚少，流媒体替代尚早",
        },
        "arms": [
            {"name": "A 坚持门店模式", "overrides": {"base_growth": 0.01, "disruptor_coupling": 0.55, "revenue_growth": 0.06}, "arm": "baseline", "mece_branches": ["门店"], "resample_variables": True},
            {"name": "B 收购/合作Netflix并建线上渠道", "overrides": {"base_growth": 0.04, "disruptor_coupling": 0.15, "revenue_growth": 0.10}, "arm": "baseline", "mece_branches": ["渠道"], "resample_variables": True},
        ],
    },
}


# Profit-chain pack — margin wiring variables, appended to each case.
# Copied verbatim from profit-chain-pack-2026-11-20/rerun/
# run_classic_profit_pack.py (including its evidence strings and the
# stream-shift comment). PROFIT MIGRATION NOTE (2026-11-23): on the
# current template these ids are TEMPLATE variables, so each entry here
# OVERRIDES the template value in place at merge. margin_base /
# margin_adoption are the two sampled draws the template attach prepends
# ahead of the case variables — that is the classic stream shift (see
# the module docstring); the case-variable order itself is unchanged.
# M2 (DIAGNOSIS-2015.md §4): margin_base is DIRECTLY sampled —
# triangular(mode-0.02, mode, mode+0.02), mode = decision-year
# profit/revenue — replacing the Track B profit/revenue ratio.
def _margin_wiring_variables(margin_mode, margin_longrun, base_tag,
                             base_evidence, longrun_evidence):
    return [
        {
            "id": "margin_base",
            "unit": "rate",
            "distribution": triangular(margin_mode - 0.02, margin_mode, margin_mode + 0.02),
            "evidence_ref": base_evidence,
            "description": "起始利润率（决策年利润/收入，众数；直接抽样，M2）",
            "scope_tags": [base_tag],
        },
        {
            "id": "margin_longrun",
            "unit": "rate",
            "distribution": {"type": "fixed", "value": margin_longrun},
            "evidence_ref": longrun_evidence,
            "description": "利润率均值回归锚（决策年前两年平均利润率，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "margin_reversion",
            "unit": "per-year",
            "distribution": {"type": "fixed", "value": 0.25},
            "evidence_ref": "estimate: LABELED ASSUMPTION — a quarter of the gap to the long-run mean closes per tick (round number, fixed before the run; see TRACK-B.md §4 sensitivity)",
            "description": "利润率向长期均值回归的速度（每年收敛 1/4 偏离，标注假设）",
            "scope_tags": [base_tag],
        },
        {
            "id": "margin_adoption",
            "unit": "margin points per unit adoption",
            "distribution": triangular(-0.02, 0.0, 0.02),
            "evidence_ref": "estimate: LABELED ASSUMPTION — net effect of adoption on the profit margin; mode 0 (no signed decision-time evidence: scale/learning vs price pressure)",
            "description": "每单位采用率对利润率的净效应（众数 0，标注假设）",
            "scope_tags": [base_tag],
        },
    ]


CASES["huawei"]["variables"] += _margin_wiring_variables(
    0.1318, 0.1318, "growth",
    "evidence: 2000 net margin mode = 29/220 = 0.1318 (2000 sales RMB 22B, profit RMB 2.9B; decision-time internal figures); the +-0.02 spread is a LABELED ASSUMPTION (M2 direct sampling)",
    "estimate: LABELED ASSUMPTION — FALLBACK anchor = decision-year mode 0.1318 (no reversion on average): the 1998/1999 two-year profit history could not be publicly verified — two searches confirmed only revenue (1999 RMB 12B / 1998 RMB 8.9B), no public profit figures — so the anchor takes the decision-year mode, labeled as a fallback assumption",
)
CASES["nokia"]["variables"] += _margin_wiring_variables(
    0.1338, 0.1346, "ecosystem",
    "evidence: 2006 OPERATING margin mode = 5.5/41.1 = 0.1338 (2006 operating profit EUR 5.5B on net sales EUR 41.1B, reported Jan 2007); the +-0.02 spread is a LABELED ASSUMPTION (M2 direct sampling). NOTE: Nokia's profit variable is OPERATING profit (see its evidence_ref), so this chain is an OPERATING-margin chain, not a net-margin chain.",
    "evidence: mean OPERATING margin of the two years before the decision year: 2005 4639/34191 = 13.57% and 2006 5488/41121 = 13.35%, mean 0.1346 (Nokia Q4 2006 press release 2007-01-25, known before the 2007-06-29 decision point; firewall clean). OPERATING-profit caliber — same caliber as the profit variable; the chain is an operating-margin chain.",
)


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

    # 2. Anchor run
    payload = {
        "company_id": spec["company_id"],
        "company_name": spec["company_name"],
        "market": spec["market"],
        "domain_id": "corporate",
        "actor_template": "ai_model_provider",
        "tick_count": 10,
        "seed": 7,
        "decision_time": spec["decision_time"],
        "decomposition": spec["decomposition"],
        # PROFIT MIGRATION (2026-11-23): attach the corporate template so
        # the run reads the product profit path. REQUIRED — the backend
        # merges a template only when this id is set; the e047f50 /
        # merged-tip reruns omitted it, so the corporate template was
        # never merged there (profit-chain-pack precedent).
        "variable_template_id": "builtin:corporate",
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

    # 3. Anchor ensemble
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

    # 3b. Anchor ensemble, revenue metric (Fix 3: revenue magnitude)
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
        # record child run config (verify formulas inherited + fork behavior)
        st3, body3 = call("GET", f"/runs/{child_id}")
        save(name, f"08-child-run-{tag}", st3, body3)
        # replay package for trajectory (base child run, deterministic)
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
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=["huawei", "nokia", "blockbuster", "all"], default="all")
    ap.add_argument("--skip-derive", action="store_true")
    args = ap.parse_args()
    names = ["huawei", "nokia", "blockbuster"] if args.case == "all" else [args.case]
    summary = {}
    for name in names:
        summary[name] = run_case(name, CASES[name], skip_derive=args.skip_derive)
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("\nDONE. summary -> raw/summary.json", flush=True)


if __name__ == "__main__":
    main()
