// GENERATED — do not hand-edit. Regenerate with:
//   python3 ~/workspace/research/strategy-engine/known-fixes-2026-11-20/gen-fixtures-v2.py <this file>
// Source: backtest rerun e047f50 (seed 42, trials 20), raw JSON under
// ~/workspace/research/strategy-engine/backtest-rerun-2026-11-19-e047f50/.
// DerivationRead bodies are verbatim copies of each case's 11-derive.json
// body. NarrativeDistributionSections assemble the revenue MC baseline
// stats (06b / 03b files) with the matching expected-shortfall baseline
// object and trial_values_hash (07 / 04 files). Bootstrap intervals were
// not run in the rerun, so bootstrap_intervals is honestly empty.

import type { DerivationRead, NarrativeDistributionSection } from '../api/engineTypes'

// --- Huawei2000: derive response, verbatim from raw-classic/huawei/11-derive.json ---
export const derivationReadHuawei2000: DerivationRead = {
  "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
  "rules_version": "derivation-rules-v2",
  "derivation_hash": "sha256:1a15c44b64b72b8ffe3061d5cc7faa0c493f82b4e86f476e846a0eeba2146a60",
  "family_size": 4,
  "candidates_considered": 8,
  "outcomes": [
    {
      "rule_id": "highest_p50",
      "status": "produced",
      "reason": "Selected (c55451c1-0425-45b9-978c-94eed2ba0aba, baseline).",
      "direction_name": "Highest P50",
      "source_run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 1339.6083,
      "p_loss": 0.0,
      "expected_shortfall": 1148.4527,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "most_robust",
      "status": "duplicate",
      "reason": "Selected (c55451c1-0425-45b9-978c-94eed2ba0aba, baseline), already taken by rule 'highest_p50'.",
      "direction_name": null,
      "source_run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
      "arm": "baseline",
      "duplicate_of_rule": "highest_p50",
      "p50": 1339.6083,
      "p_loss": 0.0,
      "expected_shortfall": 1148.4527,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "baseline_control",
      "status": "produced",
      "reason": "Selected (30e09171-a945-47ce-81d1-c444a5b95426, baseline).",
      "direction_name": "Baseline",
      "source_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 1137.1442,
      "p_loss": 0.0,
      "expected_shortfall": 256.125,
      "expected_shortfall_alpha": 0.05
    }
  ],
  "mappings": [
    {
      "id": "f20c39c2-1269-4a94-ab74-a8c2f01ac542",
      "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "name": "A 收缩保利润",
      "source_run_id": "09858632-2c3b-4188-8cbb-26d260a5bab3",
      "arm": "baseline",
      "mece_branches": [
        "生存"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "share_growth": 0.0,
          "revenue_growth": 0.05,
          "profit_growth": 0.05
        },
        "branch_id": "b6a34bed-e349-4c30-a513-06b3014710bb",
        "fork_step": 1,
        "override_hash": "sha256:c58bacb50aede377984a4a17978e3b3f581a4866185ff7e897907ee88dd30a88",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 0,
      "created_at": "2026-11-19T15:36:16.191093",
      "updated_at": "2026-11-19T15:36:16.191098"
    },
    {
      "id": "16314f40-a15b-4d7c-abed-ef1b5a8eb524",
      "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "name": "B 坚持投入",
      "source_run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
      "arm": "baseline",
      "mece_branches": [
        "增长"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "share_growth": 0.15,
          "revenue_growth": 0.22,
          "profit_growth": 0.18
        },
        "branch_id": "a79c8055-fdec-4e2b-9a61-f2f9af58ffe1",
        "fork_step": 1,
        "override_hash": "sha256:c58bacb50aede377984a4a17978e3b3f581a4866185ff7e897907ee88dd30a88",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 1,
      "created_at": "2026-11-19T15:36:16.191106",
      "updated_at": "2026-11-19T15:36:16.191106"
    },
    {
      "id": "06bbedd4-f54b-48aa-8b24-87b99746a205",
      "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "name": "C 聚焦国内",
      "source_run_id": "399bfbc4-4687-4f92-bcfd-73da32e21a35",
      "arm": "baseline",
      "mece_branches": [
        "增长"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "share_growth": 0.05,
          "revenue_growth": 0.12,
          "profit_growth": 0.1
        },
        "branch_id": "cfb31a8d-e9f0-468c-a113-023779845c4d",
        "fork_step": 1,
        "override_hash": "sha256:c58bacb50aede377984a4a17978e3b3f581a4866185ff7e897907ee88dd30a88",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 2,
      "created_at": "2026-11-19T15:36:16.191112",
      "updated_at": "2026-11-19T15:36:16.191113"
    },
    {
      "id": "3a994b14-27ad-45b9-a584-aff71d1e0030",
      "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "name": "Highest P50",
      "source_run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "highest_p50",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "highest_p50",
        "status": "produced",
        "reason": "Selected (c55451c1-0425-45b9-978c-94eed2ba0aba, baseline).",
        "direction_name": "Highest P50",
        "source_run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 1339.6083,
        "p_loss": 0.0,
        "expected_shortfall": 1148.4527,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:1a15c44b64b72b8ffe3061d5cc7faa0c493f82b4e86f476e846a0eeba2146a60",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 3,
      "created_at": "2026-11-19T15:36:23.575393",
      "updated_at": "2026-11-19T15:36:23.575397"
    },
    {
      "id": "f1193272-5856-4e5a-b481-645e7fea1246",
      "anchor_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "name": "Baseline",
      "source_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "baseline_control",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "baseline_control",
        "status": "produced",
        "reason": "Selected (30e09171-a945-47ce-81d1-c444a5b95426, baseline).",
        "direction_name": "Baseline",
        "source_run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 1137.1442,
        "p_loss": 0.0,
        "expected_shortfall": 256.125,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:1a15c44b64b72b8ffe3061d5cc7faa0c493f82b4e86f476e846a0eeba2146a60",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 4,
      "created_at": "2026-11-19T15:36:23.575407",
      "updated_at": "2026-11-19T15:36:23.575407"
    }
  ]
}

// --- Huawei2000: revenue distributions (B = highest_p50 direction, anchor = baseline control) ---
export const revenueDistributionBHuawei2000: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "c55451c1-0425-45b9-978c-94eed2ba0aba",
  "ensemble_id": "b66a90b7-a33f-43ad-88d0-bc1a14ef3097",
  "metric": "revenue",
  "loss_threshold": 220.0,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 1337.5514,
  "min": 1148.4527,
  "max": 1502.1027,
  "p10": 1218.2159,
  "p50": 1339.6083,
  "p90": 1448.4684,
  "stddev": 87.7723,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 1148.4527,
    "threshold": 1148.4527,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:f9777463211931c340df42844ae9090f1e73277292696c750f73dcb509c19fb0"
}

export const revenueDistributionAnchorHuawei2000: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "30e09171-a945-47ce-81d1-c444a5b95426",
  "ensemble_id": "7b13bccd-bcf0-4323-b4cf-475d3010e347",
  "metric": "revenue",
  "loss_threshold": 220.0,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 1223.9215,
  "min": 256.125,
  "max": 2614.4156,
  "p10": 449.3406,
  "p50": 1137.1442,
  "p90": 2285.2239,
  "stddev": 692.761,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 256.125,
    "threshold": 256.125,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:000505f1aa3b610f69b723a1160c52db472307b583c831260576546576fd99aa"
}

// --- Nokia2007: derive response, verbatim from raw-classic/nokia/11-derive.json ---
export const derivationReadNokia2007: DerivationRead = {
  "anchor_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
  "rules_version": "derivation-rules-v2",
  "derivation_hash": "sha256:791d36ba7474d0d92a7d4a2caf76273fecb14b60aa9256b43e58d903405c365b",
  "family_size": 3,
  "candidates_considered": 6,
  "outcomes": [
    {
      "rule_id": "highest_p50",
      "status": "produced",
      "reason": "Selected (1c8d6804-6fb2-4648-a30c-3627485594ea, baseline).",
      "direction_name": "Highest P50",
      "source_run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 39.8909,
      "p_loss": 0.6,
      "expected_shortfall": 30.2886,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "most_robust",
      "status": "duplicate",
      "reason": "Selected (1c8d6804-6fb2-4648-a30c-3627485594ea, baseline), already taken by rule 'highest_p50'.",
      "direction_name": null,
      "source_run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
      "arm": "baseline",
      "duplicate_of_rule": "highest_p50",
      "p50": 39.8909,
      "p_loss": 0.6,
      "expected_shortfall": 30.2886,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "baseline_control",
      "status": "produced",
      "reason": "Selected (453f8429-86bc-4d2b-bbd8-99894c28f1ac, baseline).",
      "direction_name": "Baseline",
      "source_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 2.1489,
      "p_loss": 1.0,
      "expected_shortfall": 0.236,
      "expected_shortfall_alpha": 0.05
    }
  ],
  "mappings": [
    {
      "id": "2a2482e5-1cf1-4ae9-a004-dcc4df4518be",
      "anchor_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "name": "A 坚持Symbian",
      "source_run_id": "5b5e035d-bf1f-4fdf-ae5b-96c11a150692",
      "arm": "baseline",
      "mece_branches": [
        "生态"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.01,
          "disruptor_coupling": 0.55,
          "revenue_growth": 0.1,
          "profit_growth": 0.08
        },
        "branch_id": "2d326890-4552-4c55-aeff-1c22e1603b06",
        "fork_step": 1,
        "override_hash": "sha256:92b3afbd8c5fb0f1d03b66449d9f2588a79043b1ad27565ef4af0ea58fc443db",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 0,
      "created_at": "2026-11-19T15:36:26.449677",
      "updated_at": "2026-11-19T15:36:26.449682"
    },
    {
      "id": "ee5e3258-e9e8-4012-b199-f949557308d8",
      "anchor_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "name": "B 转向触屏生态",
      "source_run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
      "arm": "baseline",
      "mece_branches": [
        "生态"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.02,
          "disruptor_coupling": 0.2,
          "revenue_growth": 0.12,
          "profit_growth": 0.1
        },
        "branch_id": "89539270-98ff-4db5-9d45-c6d484f8f384",
        "fork_step": 1,
        "override_hash": "sha256:92b3afbd8c5fb0f1d03b66449d9f2588a79043b1ad27565ef4af0ea58fc443db",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 1,
      "created_at": "2026-11-19T15:36:26.449690",
      "updated_at": "2026-11-19T15:36:26.449691"
    },
    {
      "id": "5d9a916b-4436-470c-b8ce-7825dd2582fa",
      "anchor_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "name": "Highest P50",
      "source_run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "highest_p50",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "highest_p50",
        "status": "produced",
        "reason": "Selected (1c8d6804-6fb2-4648-a30c-3627485594ea, baseline).",
        "direction_name": "Highest P50",
        "source_run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 39.8909,
        "p_loss": 0.6,
        "expected_shortfall": 30.2886,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:791d36ba7474d0d92a7d4a2caf76273fecb14b60aa9256b43e58d903405c365b",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 2,
      "created_at": "2026-11-19T15:36:31.724099",
      "updated_at": "2026-11-19T15:36:31.724105"
    },
    {
      "id": "38ec481e-fe43-4564-84a4-b3c878be9972",
      "anchor_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "name": "Baseline",
      "source_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "baseline_control",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "baseline_control",
        "status": "produced",
        "reason": "Selected (453f8429-86bc-4d2b-bbd8-99894c28f1ac, baseline).",
        "direction_name": "Baseline",
        "source_run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 2.1489,
        "p_loss": 1.0,
        "expected_shortfall": 0.236,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:791d36ba7474d0d92a7d4a2caf76273fecb14b60aa9256b43e58d903405c365b",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 3,
      "created_at": "2026-11-19T15:36:31.724114",
      "updated_at": "2026-11-19T15:36:31.724114"
    }
  ]
}

// --- Nokia2007: revenue distributions (B = highest_p50 direction, anchor = baseline control) ---
export const revenueDistributionBNokia2007: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "1c8d6804-6fb2-4648-a30c-3627485594ea",
  "ensemble_id": "344bd4fd-9a48-413d-881d-a79a9d5604d4",
  "metric": "revenue",
  "loss_threshold": 41.1,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 39.5079,
  "min": 30.2886,
  "max": 45.3201,
  "p10": 34.5616,
  "p50": 39.8909,
  "p90": 44.589,
  "stddev": 4.0415,
  "p_loss": 0.6,
  "expected_shortfall": {
    "value": 30.2886,
    "threshold": 30.2886,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:53ce20d8ed1840f350fb949a9beea9965fd93c7a33c240f6e5504299058f22b4"
}

export const revenueDistributionAnchorNokia2007: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "453f8429-86bc-4d2b-bbd8-99894c28f1ac",
  "ensemble_id": "a22749c6-2fae-4d72-938b-c4e578c576a7",
  "metric": "revenue",
  "loss_threshold": 41.1,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 2.872,
  "min": 0.236,
  "max": 9.8964,
  "p10": 0.5836,
  "p50": 2.1489,
  "p90": 4.9224,
  "stddev": 2.5681,
  "p_loss": 1.0,
  "expected_shortfall": {
    "value": 0.236,
    "threshold": 0.236,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:c71861eeb7bf0df2b23cf26eb0136a7214785c031a1f265f2a2ed62872f4ddee"
}

// --- Desay2015: derive response, verbatim from raw-desay/desay-2015/11-derive.json ---
export const derivationReadDesay2015: DerivationRead = {
  "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
  "rules_version": "derivation-rules-v2",
  "derivation_hash": "sha256:9f53970edde931c0d0ed3d8f2e6418d7eea90cef1ba59fcd834b8872fa314213",
  "family_size": 4,
  "candidates_considered": 8,
  "outcomes": [
    {
      "rule_id": "highest_p50",
      "status": "produced",
      "reason": "Selected (a798c506-d352-48ac-ae66-54a0e26ad14e, baseline).",
      "direction_name": "Highest P50",
      "source_run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 8778.0068,
      "p_loss": 0.0,
      "expected_shortfall": 8279.2851,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "most_robust",
      "status": "duplicate",
      "reason": "Selected (a798c506-d352-48ac-ae66-54a0e26ad14e, baseline), already taken by rule 'highest_p50'.",
      "direction_name": null,
      "source_run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
      "arm": "baseline",
      "duplicate_of_rule": "highest_p50",
      "p50": 8778.0068,
      "p_loss": 0.0,
      "expected_shortfall": 8279.2851,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "baseline_control",
      "status": "produced",
      "reason": "Selected (eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c, baseline).",
      "direction_name": "Baseline",
      "source_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 11824.7343,
      "p_loss": 0.0,
      "expected_shortfall": 9567.1614,
      "expected_shortfall_alpha": 0.05
    }
  ],
  "mappings": [
    {
      "id": "fcb09efe-b0e4-429c-b0f7-9f6cdbc76a15",
      "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "name": "A stay traditional",
      "source_run_id": "a52969e6-d260-4695-ac37-745083bf2f7b",
      "arm": "baseline",
      "mece_branches": [
        "传统"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.01,
          "share_coupling": 0.05,
          "revenue_growth": 0.06,
          "revenue_coupling": 0.02,
          "profit_growth": 0.05,
          "profit_coupling": 0.02,
          "nev_coupling": 0.1
        },
        "branch_id": "c719fe8c-82c2-43e7-86b1-043f31383cfd",
        "fork_step": 1,
        "override_hash": "sha256:b2fcfeccdd4d0d9046f1c616c55e074fea55f169f1fcc1ea663ed4bf1c0de052",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 0,
      "created_at": "2026-11-19T15:37:02.415697",
      "updated_at": "2026-11-19T15:37:02.415702"
    },
    {
      "id": "76b4ddf7-764c-4e01-bac6-0bc8008d95fc",
      "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "name": "B invest smart cockpit ADAS",
      "source_run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
      "arm": "baseline",
      "mece_branches": [
        "智能化"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.03,
          "share_coupling": 0.25,
          "revenue_growth": 0.1,
          "revenue_coupling": 0.15,
          "profit_growth": 0.08,
          "profit_coupling": 0.1,
          "nev_coupling": 0.25
        },
        "branch_id": "873556c2-1c18-473e-b9c5-7657b191c596",
        "fork_step": 1,
        "override_hash": "sha256:b2fcfeccdd4d0d9046f1c616c55e074fea55f169f1fcc1ea663ed4bf1c0de052",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 1,
      "created_at": "2026-11-19T15:37:02.415710",
      "updated_at": "2026-11-19T15:37:02.415711"
    },
    {
      "id": "55045e87-a700-45d4-9932-1321ed7222f4",
      "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "name": "C expand overseas aftermarket",
      "source_run_id": "50128f47-9311-435d-856a-8d1550aa7c4d",
      "arm": "baseline",
      "mece_branches": [
        "出海与后市场"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.02,
          "share_coupling": 0.1,
          "revenue_growth": 0.08,
          "revenue_coupling": 0.06,
          "profit_growth": 0.06,
          "profit_coupling": 0.05,
          "nev_coupling": 0.15
        },
        "branch_id": "03d00eb6-d468-4c20-9029-88b2a1d42d26",
        "fork_step": 1,
        "override_hash": "sha256:b2fcfeccdd4d0d9046f1c616c55e074fea55f169f1fcc1ea663ed4bf1c0de052",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 2,
      "created_at": "2026-11-19T15:37:02.415716",
      "updated_at": "2026-11-19T15:37:02.415717"
    },
    {
      "id": "75266231-2baa-441e-8fae-4c3b452c0bad",
      "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "name": "Highest P50",
      "source_run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "highest_p50",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "highest_p50",
        "status": "produced",
        "reason": "Selected (a798c506-d352-48ac-ae66-54a0e26ad14e, baseline).",
        "direction_name": "Highest P50",
        "source_run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 8778.0068,
        "p_loss": 0.0,
        "expected_shortfall": 8279.2851,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:9f53970edde931c0d0ed3d8f2e6418d7eea90cef1ba59fcd834b8872fa314213",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 3,
      "created_at": "2026-11-19T15:37:16.772773",
      "updated_at": "2026-11-19T15:37:16.772778"
    },
    {
      "id": "28a7222f-b47b-4ea6-8ea4-dea82eaf76c0",
      "anchor_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "name": "Baseline",
      "source_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "baseline_control",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "baseline_control",
        "status": "produced",
        "reason": "Selected (eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c, baseline).",
        "direction_name": "Baseline",
        "source_run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 11824.7343,
        "p_loss": 0.0,
        "expected_shortfall": 9567.1614,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:9f53970edde931c0d0ed3d8f2e6418d7eea90cef1ba59fcd834b8872fa314213",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 4,
      "created_at": "2026-11-19T15:37:16.772786",
      "updated_at": "2026-11-19T15:37:16.772787"
    }
  ]
}

// --- Desay2015: revenue distributions (B = highest_p50 direction, anchor = baseline control) ---
export const revenueDistributionBDesay2015: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "a798c506-d352-48ac-ae66-54a0e26ad14e",
  "ensemble_id": "38514b25-aae4-42fc-bbff-8cbba47ccc57",
  "metric": "revenue",
  "loss_threshold": 3668.25,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 8931.3802,
  "min": 8279.2851,
  "max": 10007.4034,
  "p10": 8407.7518,
  "p50": 8778.0068,
  "p90": 9626.1575,
  "stddev": 480.0901,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 8279.2851,
    "threshold": 8279.2851,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:ac62e4ec30d938f9dbee5dd0888707e3db3549a2134d3baf4f8b4c45f54e0bc0"
}

export const revenueDistributionAnchorDesay2015: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c",
  "ensemble_id": "5119b81b-e552-41be-990a-20d590ee847c",
  "metric": "revenue",
  "loss_threshold": 3668.25,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 12410.9155,
  "min": 9567.1614,
  "max": 17939.6023,
  "p10": 10123.0491,
  "p50": 11824.7343,
  "p90": 14741.5623,
  "stddev": 2155.9423,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 9567.1614,
    "threshold": 9567.1614,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:3567e8f401d5d2263154f1a30dc6365dfa8d2c6e62dd91f51b8b857901aa1dac"
}

// --- Desay2020: derive response, verbatim from raw-desay/desay-2020/11-derive.json ---
export const derivationReadDesay2020: DerivationRead = {
  "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
  "rules_version": "derivation-rules-v2",
  "derivation_hash": "sha256:3321f807d5a26646855a3de6bae3460b2ff6cafc266c9e56b3cf83243404a91b",
  "family_size": 4,
  "candidates_considered": 8,
  "outcomes": [
    {
      "rule_id": "highest_p50",
      "status": "produced",
      "reason": "Selected (53db6d63-1a8d-43a2-b46c-16cdd86ef837, baseline).",
      "direction_name": "Highest P50",
      "source_run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 38721.6944,
      "p_loss": 0.0,
      "expected_shortfall": 35802.3209,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "most_robust",
      "status": "duplicate",
      "reason": "Selected (53db6d63-1a8d-43a2-b46c-16cdd86ef837, baseline), already taken by rule 'highest_p50'.",
      "direction_name": null,
      "source_run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
      "arm": "baseline",
      "duplicate_of_rule": "highest_p50",
      "p50": 38721.6944,
      "p_loss": 0.0,
      "expected_shortfall": 35802.3209,
      "expected_shortfall_alpha": 0.05
    },
    {
      "rule_id": "baseline_control",
      "status": "produced",
      "reason": "Selected (fc7550f4-2b1d-49f5-a859-10a98036d8de, baseline).",
      "direction_name": "Baseline",
      "source_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "arm": "baseline",
      "duplicate_of_rule": null,
      "p50": 60303.1553,
      "p_loss": 0.0,
      "expected_shortfall": 48618.9141,
      "expected_shortfall_alpha": 0.05
    }
  ],
  "mappings": [
    {
      "id": "4f30fb92-a123-4c95-b026-745d4f235f6f",
      "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "name": "A moderate cockpit focused",
      "source_run_id": "47656851-dea5-4f63-9656-bb5727907112",
      "arm": "baseline",
      "mece_branches": [
        "座舱"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.02,
          "share_coupling": 0.1,
          "revenue_growth": 0.1,
          "revenue_coupling": 0.1,
          "profit_growth": 0.08,
          "profit_coupling": 0.08,
          "nev_coupling": 0.1
        },
        "branch_id": "8edd08d6-3772-4ba7-9897-30d97cea7a1c",
        "fork_step": 1,
        "override_hash": "sha256:8558a8facc8848712b64f6d0ff9f832252ab57e4959835900d9f869315427ece",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 0,
      "created_at": "2026-11-19T15:37:22.283379",
      "updated_at": "2026-11-19T15:37:22.283385"
    },
    {
      "id": "dc71cd83-fff3-4024-ae76-931dd4a848f6",
      "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "name": "B aggressive intelligent driving push",
      "source_run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
      "arm": "baseline",
      "mece_branches": [
        "智能驾驶"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.03,
          "share_coupling": 0.25,
          "revenue_growth": 0.15,
          "revenue_coupling": 0.25,
          "profit_growth": 0.12,
          "profit_coupling": 0.15,
          "nev_coupling": 0.25
        },
        "branch_id": "4c739088-31a7-4575-a0fc-33defddc781f",
        "fork_step": 1,
        "override_hash": "sha256:8558a8facc8848712b64f6d0ff9f832252ab57e4959835900d9f869315427ece",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 1,
      "created_at": "2026-11-19T15:37:22.283392",
      "updated_at": "2026-11-19T15:37:22.283393"
    },
    {
      "id": "e345ad23-6300-4405-bb4c-2e1b280f78eb",
      "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "name": "C connected services overseas",
      "source_run_id": "bfeb49f6-c91d-4e28-9aaa-3e6dc9d86854",
      "arm": "baseline",
      "mece_branches": [
        "网联与出海"
      ],
      "deliberation_id": null,
      "origin": "override",
      "rule_id": null,
      "rules_version": null,
      "rule_record": null,
      "status": "active",
      "proposal_record": null,
      "override_record": {
        "overrides": {
          "base_growth": 0.02,
          "share_coupling": 0.15,
          "revenue_growth": 0.1,
          "revenue_coupling": 0.15,
          "profit_growth": 0.08,
          "profit_coupling": 0.1,
          "nev_coupling": 0.15
        },
        "branch_id": "c82ac208-12d7-45e7-9df7-92ec4d3885d0",
        "fork_step": 1,
        "override_hash": "sha256:8558a8facc8848712b64f6d0ff9f832252ab57e4959835900d9f869315427ece",
        "resample_variables": true
      },
      "user_edited": false,
      "position": 2,
      "created_at": "2026-11-19T15:37:22.283398",
      "updated_at": "2026-11-19T15:37:22.283399"
    },
    {
      "id": "5f5d3588-6c8d-47ef-bf11-e45d5c8b9eed",
      "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "name": "Highest P50",
      "source_run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "highest_p50",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "highest_p50",
        "status": "produced",
        "reason": "Selected (53db6d63-1a8d-43a2-b46c-16cdd86ef837, baseline).",
        "direction_name": "Highest P50",
        "source_run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 38721.6944,
        "p_loss": 0.0,
        "expected_shortfall": 35802.3209,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:3321f807d5a26646855a3de6bae3460b2ff6cafc266c9e56b3cf83243404a91b",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 3,
      "created_at": "2026-11-19T15:37:37.608138",
      "updated_at": "2026-11-19T15:37:37.608145"
    },
    {
      "id": "d3aefb89-f980-403f-940e-76266d1a6984",
      "anchor_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "name": "Baseline",
      "source_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
      "arm": "baseline",
      "mece_branches": [],
      "deliberation_id": null,
      "origin": "derived",
      "rule_id": "baseline_control",
      "rules_version": "derivation-rules-v2",
      "rule_record": {
        "rule_id": "baseline_control",
        "status": "produced",
        "reason": "Selected (fc7550f4-2b1d-49f5-a859-10a98036d8de, baseline).",
        "direction_name": "Baseline",
        "source_run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
        "arm": "baseline",
        "duplicate_of_rule": null,
        "p50": 60303.1553,
        "p_loss": 0.0,
        "expected_shortfall": 48618.9141,
        "expected_shortfall_alpha": 0.05,
        "derivation_hash": "sha256:3321f807d5a26646855a3de6bae3460b2ff6cafc266c9e56b3cf83243404a91b",
        "rules_version": "derivation-rules-v2"
      },
      "status": "active",
      "proposal_record": null,
      "override_record": null,
      "user_edited": false,
      "position": 4,
      "created_at": "2026-11-19T15:37:37.608156",
      "updated_at": "2026-11-19T15:37:37.608157"
    }
  ]
}

// --- Desay2020: revenue distributions (B = highest_p50 direction, anchor = baseline control) ---
export const revenueDistributionBDesay2020: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "53db6d63-1a8d-43a2-b46c-16cdd86ef837",
  "ensemble_id": "9d5263f2-0eee-4e0a-8155-7c9f53aa4110",
  "metric": "revenue",
  "loss_threshold": 6799.06,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 39472.6814,
  "min": 35802.3209,
  "max": 45493.2542,
  "p10": 36137.8763,
  "p50": 38721.6944,
  "p90": 43693.5005,
  "stddev": 2885.9425,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 35802.3209,
    "threshold": 35802.3209,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:cc64ba5cc5262f85702f55a617da89074ba49976fdea58acaf693ee782177ccf"
}

export const revenueDistributionAnchorDesay2020: NarrativeDistributionSection = {
  "provenance": "computed",
  "run_id": "fc7550f4-2b1d-49f5-a859-10a98036d8de",
  "ensemble_id": "ca3d9e0d-4986-449f-a598-de1f6f09c0a8",
  "metric": "revenue",
  "loss_threshold": 6799.06,
  "trials": 20,
  "seed": 42,
  "arm": "baseline",
  "n": 20,
  "mean": 61488.1073,
  "min": 48618.9141,
  "max": 90662.2949,
  "p10": 50560.3128,
  "p50": 60303.1553,
  "p90": 72479.4756,
  "stddev": 9711.8978,
  "p_loss": 0.0,
  "expected_shortfall": {
    "value": 48618.9141,
    "threshold": 48618.9141,
    "tail_count": 1,
    "n": 20,
    "alpha": 0.05,
    "tail": "lower"
  },
  "bootstrap_intervals": [],
  "trial_values_hash": "sha256:3a1b3de7dd8e8e5be5abe1a22097de99ecb5b2fac233879282c72522b58315c6"
}
