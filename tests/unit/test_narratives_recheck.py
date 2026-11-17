"""Unit tests for the polish re-check (numbers + provenance verification).

Pure-function tests: no database, no LLM. The SOURCE fixture mirrors
the deterministic renderer's exact format (see render.py): header,
MECE section, one direction with distribution/drivers/signals/
pre-mortem/first-step/trace, and the provenance footer. Every
asserted number is visible in this file. One test composes a real
body through the composer + renderer to prove the check works on
genuine artifact markdown, not only on hand-written fixtures.
"""

from __future__ import annotations

from decimal import Decimal

from planagent.services.distributions.models import (
    DistributionSummary,
    MonteCarloResult,
    PairedDeltaSummary,
)
from planagent.services.narratives.composer import (
    DirectionInputs,
    NarrativeInputs,
    compose_narrative,
)
from planagent.services.narratives.models import DirectionDefinition
from planagent.services.narratives.recheck import (
    check_polish,
    extract_numbers,
    extract_provenance_counts,
)

SOURCE = """# 决策方向简报：Launch decision

锚定 Run：`run-anchor-0001` | 领域：ai | 协议：sprint13-v1 | 方向数：1

## MECE 结构 [computed]

- 主题：Should we launch?；校验：通过；3 个分支，2 个 scope 标签

## 方向 1：Go all in

- 来源：Run `run-anchor-0001`，baseline 臂，ensemble `ens-1`（20 trials，seed 42）

### 结果分布 [computed]

- 指标 cash（loss threshold 0）：P10 0 / P50 10 / P90 20；均值 10；亏损概率 0.2；n=20

### 关键驱动 [computed]

- cash：60 → 140 时结果 0 → 20（swing 20）

### 调头信号

- [computed] 门禁 cash-floor：observed 10，通过

### 事前验尸 [template]

- 尚无商议输出；请先运行 strategy-team。

### 48 小时第一步 [template]

- 尚无商议输出；请先运行 advisory-board。

### 回溯

- MECE 分支：Demand（demand）

_本简报由确定性引擎生成：[computed] 来自已存储的数值结果，[deliberated] 引自已存储的商议输出，[template] 为模板措辞，不代表分析结论。_
"""


def test_good_polish_passes_with_rewording_and_format_variants() -> None:
    polished = (
        SOURCE.replace("决策方向简报", "决策简报")
        .replace("亏损概率 0.2", "亏损概率 20%")
        .replace("60 → 140", "60.0 → 140.0")
        .replace("结果分布", "结果分布（已润色）")
        .replace(
            "尚无商议输出；请先运行 strategy-team。",
            "目前还没有商议输出，请先运行 strategy-team。",
        )
    )
    result = check_polish(SOURCE, polished)
    assert result.passed
    assert result.missing_numbers == ()
    assert result.extra_numbers == ()
    assert result.missing_marks == {}
    assert result.extra_marks == {}


def test_identical_texts_pass() -> None:
    assert check_polish(SOURCE, SOURCE).passed


def test_empty_texts_pass() -> None:
    assert check_polish("", "").passed


def test_altered_number_fails_naming_missing_and_extra() -> None:
    result = check_polish(SOURCE, SOURCE.replace("P50 10", "P50 11"))
    assert not result.passed
    assert result.missing_numbers == ("10",)
    assert result.extra_numbers == ("11",)
    assert result.missing_marks == {}
    assert result.extra_marks == {}


def test_invented_number_fails() -> None:
    result = check_polish(SOURCE, SOURCE + "\n另外还有 99 个理由。\n")
    assert not result.passed
    assert result.missing_numbers == ()
    assert result.extra_numbers == ("99",)


def test_dropped_key_figure_fails() -> None:
    result = check_polish(SOURCE, SOURCE.replace("亏损概率 0.2", "亏损概率未知"))
    assert not result.passed
    assert result.missing_numbers == ("0.2",)
    assert result.extra_numbers == ()


def test_dropped_provenance_mark_fails() -> None:
    result = check_polish(SOURCE, SOURCE.replace("### 关键驱动 [computed]", "### 关键驱动"))
    assert not result.passed
    assert result.missing_marks == {"computed": 1}
    assert result.extra_marks == {}
    assert result.missing_numbers == ()
    assert result.extra_numbers == ()


def test_altered_provenance_mark_fails() -> None:
    result = check_polish(
        SOURCE, SOURCE.replace("### 关键驱动 [computed]", "### 关键驱动 [template]")
    )
    assert not result.passed
    assert result.missing_marks == {"computed": 1}
    assert result.extra_marks == {"template": 1}


def test_added_provenance_mark_fails() -> None:
    result = check_polish(SOURCE, SOURCE.replace("### 调头信号", "### 调头信号 [computed]"))
    assert not result.passed
    assert result.missing_marks == {}
    assert result.extra_marks == {"computed": 1}


def test_footer_marks_counted_dropping_footer_fails() -> None:
    polished = SOURCE.split("_本简报由确定性引擎生成")[0]
    result = check_polish(SOURCE, polished)
    assert not result.passed
    assert result.missing_marks == {"computed": 1, "deliberated": 1, "template": 1}


def test_mark_reorder_passes_attachment_is_not_checked() -> None:
    head, rest = SOURCE.split("### 事前验尸", 1)
    pre, rest2 = rest.split("### 48 小时第一步", 1)
    first, tail = rest2.split("### 回溯", 1)
    reordered = head + "### 48 小时第一步" + first + "### 事前验尸" + pre + "### 回溯" + tail
    assert reordered != SOURCE
    assert check_polish(SOURCE, reordered).passed


def test_marks_are_case_sensitive() -> None:
    result = check_polish(SOURCE, SOURCE.replace("[computed]", "[Computed]", 1))
    assert not result.passed
    assert result.missing_marks == {"computed": 1}


def test_other_bracketed_tokens_are_not_marks() -> None:
    # Only the three known kinds are marks; other bracketed tokens are
    # ignored by design (documented limit in recheck.py).
    assert check_polish("[see note] 10", "[see note] [estimated] 10").passed
    assert extract_provenance_counts("[see note] [estimated]") == {
        "computed": 0,
        "deliberated": 0,
        "template": 0,
    }


def test_extract_numbers_boundaries_identifiers_and_spans() -> None:
    text = (
        "P50 10, v0, n=20, -3, 1,000, 20%, 1e3, delib-strategy-1, "
        "`abc-123`, 1.2.3, 09c57c8c-df4c-440d-8aec-979588b4cb28"
    )
    assert extract_numbers(text) == (
        Decimal(10),
        Decimal(20),
        Decimal(-3),
        Decimal(1000),
        Decimal("0.2"),
        Decimal(1000),
    )


def test_extract_numbers_percent_differs_from_plain() -> None:
    assert extract_numbers("20%") == (Decimal("0.2"),)
    assert extract_numbers("20 %") == (Decimal("0.2"),)
    assert extract_numbers("20") == (Decimal(20),)


def test_extract_numbers_thousands_and_decimal_tolerance() -> None:
    assert extract_numbers("1,000") == extract_numbers("1000")
    assert extract_numbers("10.0") == extract_numbers("10")
    assert extract_numbers("0.10") == extract_numbers("0.1")
    assert extract_numbers("1e3") == extract_numbers("1000")
    assert extract_numbers("0.333333") != extract_numbers("0.333334")


def test_extract_numbers_hyphen_range_yields_first_endpoint_only() -> None:
    # A digit run after a hyphen is part of an identifier, not a
    # number; both sides use the same rule, so preserved forms pass.
    assert extract_numbers("range 10-20 clients") == (Decimal(10),)
    assert check_polish("range 10-20 clients", "range 10-20 clients").passed


def test_negative_number_sign_change_fails() -> None:
    result = check_polish("ES -3 [computed]", "ES 3 [computed]")
    assert not result.passed
    assert result.missing_numbers == ("-3",)
    assert result.extra_numbers == ("3",)


def test_multiplicity_matters_duplicated_number_fails() -> None:
    result = check_polish("10 and 10", "10 and 10 and 10")
    assert not result.passed
    assert result.extra_numbers == ("10",)
    assert check_polish("10 and 10", "10 and 10").passed


def test_code_span_id_digits_ignored_even_without_backticks_in_polish() -> None:
    source = "Run `09c57c8c-df4c-440d-8aec-979588b4cb28` scored 10 [computed]"
    polished = "Run 09c57c8c-df4c-440d-8aec-979588b4cb28 scored 10 [computed]"
    assert check_polish(source, polished).passed


def test_describe_names_every_difference() -> None:
    result = check_polish(
        SOURCE, SOURCE.replace("P50 10", "P50 11").replace("[computed]", "[template]", 1)
    )
    assert not result.passed
    description = result.describe()
    assert "numbers missing from polished text: 10" in description
    assert "numbers invented in polished text: 11" in description
    assert "provenance marks missing: [computed] x1" in description
    assert "provenance marks added: [template] x1" in description


def test_describe_passed_message() -> None:
    assert "passed" in check_polish(SOURCE, SOURCE).describe()


def _real_markdown() -> str:
    summary = DistributionSummary(
        n=20, mean=10.0, min=0.0, max=20.0, p10=0.0, p50=10.0, p90=20.0, stddev=1.0, p_loss=0.2
    )
    ensemble = MonteCarloResult(
        ensemble_id="ens-run-anchor-0001",
        base_run_id="run-anchor-0001",
        trials=20,
        seed=42,
        metric="cash",
        loss_threshold=0.0,
        strategy_levers={},
        baseline=summary,
        strategy=summary,
        paired=PairedDeltaSummary(
            n=20, mean_delta=1.0, p10=0.0, p50=1.0, p90=2.0, p_strategy_better=0.6
        ),
        trial_run_ids={},
        protocol="sprint3-v1",
    )
    definition = DirectionDefinition(
        name="Go all in", source_run_id="run-anchor-0001", arm="baseline"
    )
    inputs = NarrativeInputs(
        anchor_run_id="run-anchor-0001",
        domain_id="ai",
        request_topic="Launch decision",
        mece_tree=None,
        mece_validation=None,
        directions=[DirectionInputs(definition=definition, ensemble=ensemble)],
    )
    return compose_narrative(inputs).body.markdown


def test_real_rendered_markdown_good_polish_passes() -> None:
    markdown = _real_markdown()
    assert "P10 0 / P50 10 / P90 20" in markdown
    polished = markdown.replace("决策方向简报", "决策简报").replace("亏损概率 0.2", "亏损概率 20%")
    assert check_polish(markdown, polished).passed


def test_real_rendered_markdown_altered_number_fails() -> None:
    markdown = _real_markdown()
    result = check_polish(markdown, markdown.replace("P50 10", "P50 11", 1))
    assert not result.passed
    assert result.missing_numbers == ("10",)
    assert result.extra_numbers == ("11",)
