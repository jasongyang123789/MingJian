"""Versioned prompt template library (Sprint 6, PRD delta D9).

Templates extracted/adapted from the code-verified strategy skills in the
research record. Templates are DATA, not code: rendering is a pure,
byte-stable function of the declared slots, and no template performs any
numeric computation — numbers enter through the ``context`` slot, rendered
from engine artifacts by :mod:`planagent.services.skills.context`.

Every template carries provenance (source repo + file + license note).
MIT-licensed sources are adapted with attribution; the flingjie
strategic-issue-tree repo declares no license, so its template follows
the workflow structure with original wording and says so.

Template versions are part of the audit trail: every stored stage output
records the template id + version that produced it, so a prompt change
never silently rewrites history.

Sprint 15 (templates v2): live runs on 2026-11-16 showed prompt prose
inviting JSON shapes the contracts forbid (an object where a list of
strings is required, nested objects where flat strings are required),
and the intake prompt referenced a framework index it never supplied.
The v2 prompts specify the exact shape of every output key, and the
framework index from the McKinsey skill source is rendered into the
intake prompt from :data:`FRAMEWORK_INDEX`. Prompt semantics are
otherwise unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from string import Formatter

_TEMPLATE_VERSION = "2"

# Placeholders use ``{slot}``; literal braces in template text use the
# ``str.format`` escapes ``{{`` and ``}}``.
_PLACEHOLDER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_JSON_ONLY = (
    "Return valid JSON only, matching the shape described above. "
    "Do not compute new numbers: every number you cite must come from the "
    "context block above. Argue about the numbers; do not invent, adjust, "
    "or recompute them. Write in {output_language}."
)


@dataclass(frozen=True)
class SkillTemplate:
    """One versioned prompt template with explicit provenance."""

    id: str
    version: str
    title: str
    source_repo: str
    source_file: str
    license_note: str
    system_prompt: str
    user_template: str
    slots: tuple[str, ...]
    max_tokens: int = 1500


# ---------------------------------------------------------------------------
# Shared slot glossaries (adapted from the skill sources; see provenance
# on the templates that consume them).
# ---------------------------------------------------------------------------

# McKinsey Step 5 option-generator mandates: divergence is the point.
OPTION_MANDATES = {
    "bull": (
        "Maximize upside/growth. Propose the boldest defensible move; "
        "assume resources can be found."
    ),
    "lean": (
        "Maximize resilience/efficiency. Propose the cheapest, "
        "lowest-risk, fastest-to-reverse path."
    ),
    "contrarian": (
        "Do the opposite of the obvious play. Assume the consensus move "
        "is forbidden; propose what you would do instead."
    ),
}

# Advisory-board lens briefs (interpretive frameworks inspired by publicly
# documented principles; never presented as the named figures speaking).
LENS_BRIEFS = {
    "product_clarity": (
        "Product Clarity. Focus: simplicity, focus, product quality, "
        "story, taste, memorability. Reduce complexity; reject features "
        "or messages without a decisive purpose."
    ),
    "risk_capital": (
        "Risk and Capital. Focus: downside, incentives, durability, "
        "capital discipline, margin of safety. Make the failure path "
        "concrete; check economics before recommending growth."
    ),
    "scale_systems": (
        "Scale and Systems. Focus: customer value, mechanisms, "
        "repeatability, experimentation, operating leverage, delivery "
        "capacity. Require proof before scale; prefer mechanisms over "
        "slogans."
    ),
    "offer_strength": (
        "Offer Strength. Focus: demand, value, price, execution, sales "
        "friction, time-to-result. Use real buying behavior over "
        "compliments; never recommend fake scarcity or overpromising."
    ),
    "future_self": (
        "Future Self. Focus: long-term alignment, regret, identity, "
        "freedom, opportunity cost. Do not ignore present cash, "
        "evidence, or operational reality; distinguish long-term "
        "wisdom from comfortable avoidance."
    ),
}

LENS_QUESTIONS = {
    "product_clarity": "Is this clear, focused, and worth building?",
    "risk_capital": "Is this rational, durable, and worth the risk?",
    "scale_systems": "Does this create customer value and scale without breaking delivery?",
    "offer_strength": "Is the offer strong enough to win now?",
    "future_self": "Will the decision-maker be proud of this decision later?",
}

_DECISION_CRITERIA = "attractiveness, feasibility, risk, economics, strategic fit"

# Public name: the default criteria string passed to filter/tournament stages.
DECISION_CRITERIA = _DECISION_CRITERIA

# Framework index adapted from the McKinsey skill's "Framework index"
# section (SKILL.md; MIT — adapted with attribution, same license note
# as the templates that consume it). Sprint 15: the v1 intake prompt
# referenced "the index" without supplying it, so a live model
# returned an empty frameworks list and asked which index to use. The
# index is now rendered into the intake prompt verbatim from this
# constant; framework names must be copied exactly.
FRAMEWORK_INDEX: tuple[tuple[str, str, str], ...] = (
    # (name, group, when to use)
    (
        "situation-assessment",
        "Diagnosis & framing",
        "Factual baseline before any direction; almost always wave 1.",
    ),
    (
        "growth-barriers",
        "Diagnosis & framing",
        "Growth is stuck; leadership debates symptoms.",
    ),
    (
        "assumption-audit",
        "Diagnosis & framing",
        "Strategy leans on possibly weak beliefs; also the verify-assumptions panel lens.",
    ),
    (
        "market-mapping",
        "Market & competition",
        "Size and segment the market; find white space.",
    ),
    ("competitive-intel", "Market & competition", "Predict what rivals will do."),
    (
        "customer-segmentation",
        "Market & competition",
        "Sharper customer groups for the decision.",
    ),
    (
        "profit-pool-analysis",
        "Market & competition",
        "Where value is created and captured.",
    ),
    (
        "strategic-options",
        "Strategic choice & economics",
        "Alternatives and criteria before commitment; core for merger/choice.",
    ),
    (
        "pricing-strategy",
        "Strategic choice & economics",
        "Pricing power, discounting, or monetization unclear.",
    ),
    (
        "business-case-builder",
        "Strategic choice & economics",
        "Decision needs economics, sensitivities, risks.",
    ),
    ("portfolio-review", "Strategic choice & economics", "Allocate resources across bets."),
    (
        "operating-model-design",
        "Operating model & execution",
        "Translate strategy into how work runs.",
    ),
    (
        "initiative-prioritizer",
        "Operating model & execution",
        "Too many initiatives competing for attention.",
    ),
    (
        "transformation-roadmap",
        "Operating model & execution",
        "Strategy becomes phased execution with owners.",
    ),
    (
        "war-gaming",
        "Risk, performance & value governance",
        "Stress-test strategy before launch; the verify-wargame panel lens (loops in deep mode).",
    ),
    (
        "risk-and-mitigation",
        "Risk, performance & value governance",
        "Strategic risk gets an owner and a response plan.",
    ),
    (
        "kpi-architect",
        "Risk, performance & value governance",
        "Metrics are noisy, lagging, or performative.",
    ),
    (
        "value-realization",
        "Risk, performance & value governance",
        "Benefits must be tracked after launch.",
    ),
    (
        "stakeholder-alignment",
        "Alignment & executive communication",
        "Pre-wire the recommendation before the meeting.",
    ),
    (
        "narrative-builder",
        "Alignment & executive communication",
        "The story must land in 60 seconds (Pyramid/SCQA); the synthesis step.",
    ),
    (
        "decision-memo",
        "Alignment & executive communication",
        "A clear recommendation in writing; the deliverable.",
    ),
)

_FRAMEWORK_INDEX_BLOCK = (
    "Framework index — copy framework names EXACTLY from this list; "
    "do not invent framework names:\n"
    + "\n".join(f"- {name} [{group}]: {when}" for name, group, when in FRAMEWORK_INDEX)
)


def _template(
    template_id: str,
    title: str,
    source_repo: str,
    source_file: str,
    license_note: str,
    system_prompt: str,
    user_template: str,
    slots: tuple[str, ...],
    max_tokens: int = 1500,
) -> SkillTemplate:
    return SkillTemplate(
        id=template_id,
        version=_TEMPLATE_VERSION,
        title=title,
        source_repo=source_repo,
        source_file=source_file,
        license_note=license_note,
        system_prompt=system_prompt,
        user_template=user_template,
        slots=slots,
        max_tokens=max_tokens,
    )


_MCKINSEY_REPO = "mckinsey-strategy-team (github.com, Joost de Leij)"
_MCKINSEY_LICENSE = "MIT — adapted with attribution; see source LICENSE."
_ADVISORY_REPO = "5-persona-advisory-board (MIT)"
_ADVISORY_LICENSE = "MIT — adapted with attribution; see source LICENSE."
_GAMBIT_REPO = "gambit (github.com/skyf0xx/gambit)"
_GAMBIT_LICENSE = "MIT — adapted with attribution; see source LICENSE."
_FLINGJIE_REPO = "flingjie/strategic-issue-tree"
_FLINGJIE_LICENSE = (
    "No license declared in the source repo — workflow structure adapted, "
    "wording is original; no source text copied."
)


TEMPLATES: dict[str, SkillTemplate] = {}


def _register(template: SkillTemplate) -> SkillTemplate:
    TEMPLATES[template.id] = template
    return template


_register(
    _template(
        "mckinsey.intake_classify",
        "Intake + classify (Steps 0-1)",
        _MCKINSEY_REPO,
        "SKILL.md (Steps 0-1) + Framework index",
        _MCKINSEY_LICENSE,
        "You are the team lead of a McKinsey-style strategy team. "
        "Your job in this step is intake and classification only: restate "
        "the problem precisely, name the real decision question, classify "
        "the engagement, and produce a short engagement plan. Do not "
        "diagnose, generate options, or recommend yet.",
        "Strategic question (one line): {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        + _FRAMEWORK_INDEX_BLOCK
        + "\n\n"
        "Produce the engagement plan as JSON with keys: problem_statement "
        "(a single string, 1-2 lines), decision_question (a single string, "
        "1-2 lines), engagement_type (a single string, e.g. growth stalled, "
        "merger/M&A, pricing, new market, portfolio allocation), audience "
        "(a single string), constraints (a list of strings), stakes "
        "(standard or deep — deep only when the decision is hard to reverse "
        "or bet-the-company), frameworks (a list of strings: framework "
        "names copied exactly from the index above that fit this "
        "engagement; choose at least one when any fits), wave_plan (a list "
        "of strings, one string per assignment: who runs in wave A, which "
        "option mandates run in wave B, who sits on the verifier panel — "
        "write each assignment as one plain string, never a nested "
        "object), open_questions (a list of strings).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.diagnose",
        "Wave A — diagnose (situation assessment)",
        _MCKINSEY_REPO,
        "references/01-diagnosis-and-framing/situation-assessment.md",
        _MCKINSEY_LICENSE,
        "You are the diagnose teammate on a strategy team. Apply "
        "situation assessment strictly to THIS question: build the factual "
        "baseline before any direction is chosen. No generic theory — "
        "concrete findings, with explicit assumptions where data is "
        "missing. The market teammate works in parallel; do not wait for "
        "it and do not duplicate its market/competitor analysis.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Engagement plan:\n{intake}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the diagnosis as JSON with keys: findings (list of "
        "statements, each grounded in the context), assumptions (list of "
        "explicit assumptions made where data is missing), barriers (list "
        "of growth/diagnosis barriers found), open_questions (list).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "intake", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.market_map",
        "Wave A — map the market (market mapping + competitive intel)",
        _MCKINSEY_REPO,
        "references/02-market-and-competitive-intelligence/market-mapping.md "
        "+ competitive-intel.md",
        _MCKINSEY_LICENSE,
        "You are the market teammate on a strategy team. Apply market "
        "mapping and competitive intelligence strictly to THIS question: "
        "size and segment the market, find white space, and predict what "
        "rivals will do. No generic theory — concrete findings, with "
        "explicit assumptions where data is missing.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Engagement plan:\n{intake}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the market map as JSON with keys: summary (a single "
        "string, 2-3 lines), segments (a list of strings), competitors (a "
        "list of strings; each string names one competitor and its likely "
        "move in a single line — never return objects), white_space (a "
        "list of strings), profit_pools (a list of strings), threats (a "
        "list of strings).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "intake", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.option_generate",
        "Wave B — generate options from one mandate",
        _MCKINSEY_REPO,
        "SKILL.md (Step 5) + references/03-strategic-choice-and-economics/strategic-options.md",
        _MCKINSEY_LICENSE,
        "You are an option-generator teammate on a strategy team. "
        "Generate divergent strategic options from your assigned mandate "
        "only. Divergence is the point: do not hedge toward the middle "
        "and do not reproduce the obvious consensus option. Each option "
        "must state what must be true for it to work.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Your mandate ({mandate_name}): {mandate}\n\n"
        "Engagement plan:\n{intake}\n\n"
        "Diagnosis:\n{diagnosis}\n\n"
        "Market map:\n{market_map}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce 2-3 distinct options as JSON with key: options (list, "
        "each with name, description, upside, trade_off, "
        "what_must_be_true (list)).\n\n" + _JSON_ONLY,
        (
            "topic",
            "decision_question",
            "context",
            "intake",
            "diagnosis",
            "market_map",
            "mandate_name",
            "mandate",
            "output_language",
        ),
    )
)

_register(
    _template(
        "mckinsey.filter_shortlist",
        "Wave B — filter: dedupe, score, shortlist (lead)",
        _MCKINSEY_REPO,
        "SKILL.md (Step 5, lead filter)",
        _MCKINSEY_LICENSE,
        "You are the team lead filtering generated options. Dedupe "
        "overlapping options, drop dominated ones, and score the "
        "survivors against the decision criteria. Keep the 2-3 strongest. "
        "Do not invent new options; filter only what was generated.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Decision criteria: {criteria}\n\n"
        "Generated option sets:\n{option_sets}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the shortlist as JSON with keys: ranked (a list of "
        "objects, each with name (a string), description (a string), "
        "scores (an object mapping each criterion name to one 0-10 "
        "number), rationale (a string)), dropped (a list of objects, each "
        "with name (a string: the dropped option name) and reason (a "
        "string: one line)).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "option_sets", "criteria", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.synthesize",
        "Synthesize the draft recommendation (Pyramid / SCQA)",
        _MCKINSEY_REPO,
        "SKILL.md (Step 6) + references/06-alignment-and-executive-communication/narrative-builder.md",
        _MCKINSEY_LICENSE,
        "You are the team lead synthesizing the draft recommendation. "
        "Use the Pyramid Principle / SCQA: governing thought, then three "
        "supporting arguments with backing, then the recommended option. "
        "Name the load-bearing assumptions explicitly — a verifier panel "
        "attacks them next, so do not bury them.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Shortlist:\n{shortlist}\n\n"
        "Diagnosis:\n{diagnosis}\n\n"
        "Market map:\n{market_map}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the draft as JSON with keys: governing_thought (a single "
        "string), arguments (a list of objects, each with claim (a string) "
        "and backing (a string)), recommended_option (a single string: a "
        "name from the shortlist), load_bearing_assumptions (a list of "
        "strings — every assumption the recommendation rests on), "
        "alternatives_considered (a list of strings; each string names one "
        "shortlist option not recommended and gives its one-line reason — "
        "never return objects).\n\n" + _JSON_ONLY,
        (
            "topic",
            "decision_question",
            "context",
            "shortlist",
            "diagnosis",
            "market_map",
            "output_language",
        ),
    )
)

_register(
    _template(
        "mckinsey.verify_assumptions",
        "Verifier panel — assumption audit",
        _MCKINSEY_REPO,
        "references/01-diagnosis-and-framing/assumption-audit.md",
        _MCKINSEY_LICENSE,
        "You are the assumption-audit verifier on a strategy panel. "
        "Attack the draft's load-bearing assumptions: which beliefs are "
        "weakest, and where does the logic break if one is wrong? Grade "
        "each assumption by importance and evidence strength, and turn "
        "weak load-bearing assumptions into concrete tests. You see only "
        "this lens; other verifiers cover war-gaming and execution.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Draft recommendation under attack:\n{draft}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the audit as JSON with keys: assumptions (list, each "
        "with assumption, category, importance (an integer from 1 to 5), "
        "evidence_strength "
        "(strong/moderate/weak/speculative), risk), load_bearing (list of "
        "the assumptions that carry the recommendation), tests (list of "
        "concrete validation tests for weak load-bearing assumptions), "
        "fatal_flags (list of assumption statements you judge fatal to "
        "the recommendation if wrong — use the exact assumption wording).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "draft", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.verify_wargame",
        "Verifier panel — war game",
        _MCKINSEY_REPO,
        "references/05-risk-performance-and-value-governance/war-gaming.md",
        _MCKINSEY_LICENSE,
        "You are the war-game verifier on a strategy panel. "
        "Pressure-test the draft before reality does: build base, "
        "adverse, and aggressive scenarios across competitor, customer, "
        "market, regulatory, operational, and financial dimensions. "
        "Include likely scenarios AND painful ones. Make early warning "
        "signals observable and tie responses to owners.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Draft recommendation under attack:\n{draft}\n\n"
        "Prior war-game rounds (do not repeat findings already raised; "
        "hunt for NEW risks):\n{prior_rounds}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the war game as JSON with keys: scenarios (list, each "
        "with name, trigger, impact, likelihood, severity), "
        "vulnerabilities (list, each with weak_point, why_it_matters, "
        "mitigation), playbook (list, each with signal, response, owner), "
        "fatal_flags (list of weak-point statements you judge fatal to "
        "the recommendation — use exact wording).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "draft", "prior_rounds", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.verify_execution",
        "Verifier panel — execution + economics",
        _MCKINSEY_REPO,
        "references/04-operating-model-and-execution/operating-model-design.md "
        "+ references/05-risk-performance-and-value-governance/risk-and-mitigation.md",
        _MCKINSEY_LICENSE,
        "You are the execution verifier on a strategy panel. Attack the "
        "draft from the operating side: can the organization actually "
        "execute this, and do the economics survive a bad case? Give "
        "every risk an owner and a response plan.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Draft recommendation under attack:\n{draft}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the review as JSON with keys: feasibility (assessment "
        "of whether the organization can execute this), risks (list, each "
        "with risk, mitigation, owner), economics_survive_bad_case "
        "(assessment), fatal_flags (list of risk statements you judge "
        "fatal to the recommendation — use exact wording).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "draft", "output_language"),
    )
)

_register(
    _template(
        "mckinsey.tournament_judge",
        "Deep mode — pairwise tournament judging",
        _MCKINSEY_REPO,
        "SKILL.md (Step 7, deep mode tournament)",
        _MCKINSEY_LICENSE,
        "You are a tournament judge comparing exactly two surviving "
        "options pairwise on the decision criteria. Pick one winner. "
        "Do not average opinions and do not declare a tie: judge the "
        "pair on the criteria and say why the winner wins.",
        "Strategic question: {topic}\n"
        "Decision question: {decision_question}\n\n"
        "Decision criteria: {criteria}\n\n"
        "Option A:\n{option_a}\n\n"
        "Option B:\n{option_b}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the judgment as JSON with keys: winner (a single string: "
        "the winning option name, exactly as given), loser (a single "
        "string), rationale (a single string), criteria_scores (an object "
        "mapping each criterion name to one 0-10 number — the winner's "
        "absolute scores).\n\n" + _JSON_ONLY,
        (
            "topic",
            "decision_question",
            "context",
            "option_a",
            "option_b",
            "criteria",
            "output_language",
        ),
    )
)

_register(
    _template(
        "advisory.crit_intake",
        "CRIT intake (Context, Role, Interview, Task)",
        _ADVISORY_REPO,
        "SKILL.md (CRIT Intake)",
        _ADVISORY_LICENSE,
        "You run the CRIT intake for an advisory board: Context, Role, "
        "Interview, Task. Extract the decision, real alternatives "
        "(including do-nothing when credible), context, evidence, "
        "economics, constraints, success measure, current preference, "
        "and reversibility from what is given. Ask only questions whose "
        "answers could materially change the verdict — at most three. "
        "If interaction is unavailable, state the missing context and "
        "assumptions, then proceed.",
        "Decision: {decision}\n"
        "Options offered: {options}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the intake as JSON with keys: decision (a single "
        "string), options (a list of strings: plain option names only, no "
        "descriptions and no nested objects), context (a single flat "
        "string, never a nested object), evidence (a single flat string "
        "covering known facts and important unknowns, never a nested "
        "object), economics (a single flat string, never a nested object), "
        "constraints (a list of strings), success (a single flat string "
        "stating the measurable outcome and deadline, never a nested "
        "object), current_preference (a single flat string, never a nested "
        "object), reversibility (a single flat string covering what can be "
        "tested cheaply vs what creates lasting downside, never a nested "
        "object), assumptions (a list of strings), questions (a list of "
        "strings, at most 3).\n\n" + _JSON_ONLY,
        ("decision", "options", "context", "output_language"),
    )
)

_register(
    _template(
        "advisory.lens_position",
        "Round 1 — independent lens position",
        _ADVISORY_REPO,
        "SKILL.md (Five Lenses + Round 1)",
        _ADVISORY_LICENSE,
        "You are one lens of an advisory board. The five lenses are "
        "interpretive frameworks inspired by publicly documented business "
        "principles. You are NOT the named person, do not speak as them, "
        "and do not claim endorsement or affiliation. Evaluate every "
        "credible option independently, before seeing other positions. "
        "Keep your view genuinely distinct: do not produce generic advice "
        "any lens could have written.",
        "Lens: {lens_name}\n"
        "Lens brief: {lens_brief}\n"
        "Key question: {lens_question}\n\n"
        "Decision: {decision}\n"
        "Options: {options}\n\n"
        "Intake:\n{intake}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce your position as JSON with keys: lens (a single string), "
        "option_scores (an object mapping each option name to one 0-10 "
        "number), confidence (low, medium, or high), decisive_evidence (a "
        "single string), primary_upside (a single string), "
        "primary_failure_mode (a single string), opening_recommendation "
        "(a single string), risk_veto (null, or an object with "
        "failure_path, evidence, severity, mitigation — each a string — "
        "only for a credible ruin risk that cannot be averaged away; "
        "speculative fear is not a veto).\n\n" + _JSON_ONLY,
        (
            "decision",
            "options",
            "context",
            "intake",
            "lens_name",
            "lens_brief",
            "lens_question",
            "output_language",
        ),
    )
)

_register(
    _template(
        "advisory.lens_revision",
        "Round 3 — revision and ratification",
        _ADVISORY_REPO,
        "SKILL.md (Round 3)",
        _ADVISORY_LICENSE,
        "You are one lens of an advisory board, revising after forced "
        "debate. Submit your final position independently. A changed "
        "score needs a decision-relevant reason — say what changed or "
        "did not change and why. Preserve any credible unresolved "
        "objection; do not manufacture agreement.",
        "Lens: {lens_name}\n"
        "Lens brief: {lens_brief}\n\n"
        "Decision: {decision}\n"
        "Options: {options}\n\n"
        "Your Round 1 position:\n{own_position}\n\n"
        "Forced debate:\n{debate}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce your revision as JSON with keys: lens (a single string), "
        "final_option (a single string), revised_scores (an object "
        "mapping each option name to one 0-10 number), confidence (low, "
        "medium, or high), what_changed (a single string), "
        "required_conditions (a list of strings), kill_criterion (a "
        "single string), unresolved_objection (a single string).\n\n" + _JSON_ONLY,
        (
            "decision",
            "options",
            "context",
            "lens_name",
            "lens_brief",
            "own_position",
            "debate",
            "output_language",
        ),
    )
)

_register(
    _template(
        "advisory.forced_debate",
        "Round 2 — forced debate",
        _ADVISORY_REPO,
        "SKILL.md (Round 2 + anti-groupthink rule)",
        _ADVISORY_LICENSE,
        "You chair the forced debate of an advisory board. Select the "
        "2-4 disagreements that could change the decision. For each, "
        "name the trade-off, state the strongest case for each side, "
        "require direct rebuttals, identify evidence that would settle "
        "it, and propose the cheapest useful test. Preserve a credible "
        "minority objection. Do not manufacture theatrical disagreement "
        "when evidence is one-sided.",
        "Decision: {decision}\n"
        "Options: {options}\n\n"
        "Round 1 positions:\n{positions}\n\n"
        "{unanimity_note}\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the debate as JSON with keys: disagreements (list, each "
        "with trade_off, case_a, case_b, rebuttals (list), "
        "settling_evidence, cheapest_test), minority_objection.\n\n" + _JSON_ONLY,
        ("decision", "options", "context", "positions", "unanimity_note", "output_language"),
    )
)

_register(
    _template(
        "advisory.chair_synthesis",
        "Chair synthesis — decision contract",
        _ADVISORY_REPO,
        "SKILL.md (Decision Logic + Decision Contract)",
        _ADVISORY_LICENSE,
        "You chair an advisory board and write the decision contract. "
        "Use evidence, not headcount: the weighted direction is a "
        "summary, never an automatic answer. Distinguish 'choose now' "
        "from 'validate before choosing'. A credible ruin-risk warning "
        "cannot be averaged away — carry vetoes into the contract. The "
        "user remains the decision owner; never present the verdict as "
        "certainty.",
        "Decision: {decision}\n"
        "Options: {options}\n\n"
        "Round 1 positions:\n{positions}\n\n"
        "Forced debate:\n{debate}\n\n"
        "Round 3 revisions:\n{revisions}\n\n"
        "Weighted direction (summary only, computed from lens scores — "
        "not the answer):\n{weighted_direction}\n\n"
        "Risk vetoes raised:\n{vetoes}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the decision contract as JSON with keys: verdict "
        "(choose, reject, or validate_first), why_now (a single string), "
        "conditions (a list of strings), minority_report (a single "
        "string), cheapest_validation_test (a single string), go_threshold "
        "(a single string), kill_criterion (a single string), owner (a "
        "single string), deadline (a single string), review_date (a "
        "single string), next_action (a single string), do_not_do (a "
        "single string), lens_weights (an object mapping each lens name "
        "to a relevance integer from 1 to 3), assumptions (a list of "
        "strings).\n\n" + _JSON_ONLY,
        (
            "decision",
            "options",
            "context",
            "positions",
            "debate",
            "revisions",
            "weighted_direction",
            "vetoes",
            "output_language",
        ),
    )
)

_register(
    _template(
        "gambit.premortem",
        "Pre-mortem — prospective hindsight",
        _GAMBIT_REPO,
        "skills/premortem/SKILL.md",
        _GAMBIT_LICENSE,
        "You run a pre-mortem. The failure is stipulated, not "
        "hypothesized: it is the failure date and the plan HAS failed. "
        "Work backwards and explain why. This surfaces failure modes "
        "that outside-in red-teaming reliably misses — especially ones "
        "the decision-maker privately suspects but has not said aloud. "
        "Do not hedge the premise and do not re-argue whether failure "
        "was likely.",
        "Plan under test: {topic}\n"
        "Decision question: {decision_question}\n"
        "It is {failure_date}. The plan has failed.\n\n"
        "Draft recommendation:\n{draft}\n\n"
        "Context (facts from the decision engine — treat as given):\n{context}\n\n"
        "Produce the pre-mortem as JSON with keys: failure_narrative "
        "(how the failure unfolded), failure_modes (list, each with "
        "mode, cause, early_signal, prevention), fatal_flags (list of "
        "failure-mode statements you judge fatal — use exact wording).\n\n" + _JSON_ONLY,
        ("topic", "decision_question", "context", "draft", "failure_date", "output_language"),
    )
)

_register(
    _template(
        "mece.propose_tree",
        "MECE authoring aid — propose a decomposition tree",
        _FLINGJIE_REPO,
        "SKILL.md (Phases 1-2) + templates/issue_tree.md",
        _FLINGJIE_LICENSE,
        "You are a strategy consultant helping structure a decision. "
        "Your job is to PROPOSE a decomposition tree — you do not decide "
        "whether it is MECE. A code validator checks the tree afterwards, "
        "and a failing tree is refused no matter how good it reads. "
        "Follow the checklist: the root is the confirmed topic, stated "
        "once; branches are statement-form noun phrases, not questions; "
        "every branch carries atomic scope tags; children partition the "
        "parent's scope — siblings must not share tags, and together "
        "they must cover every parent tag; 2-4 children per branch; at "
        "most 2 levels below the root in this proposal. Adapt any "
        "suggested dimensions to the user's concrete context; never copy "
        "abstract labels verbatim.",
        "Decision topic: {topic}\n\n"
        "Context:\n{context}\n\n"
        "Suggested dimensions (adapt to context; add, drop, or rename "
        "as the topic demands):\n{dimensions}\n\n"
        "Existing tree to revise (empty when this is a fresh proposal):\n{existing_tree}\n\n"
        "Propose the tree as JSON with keys: topic, root (an object with "
        "name, scope (list of atomic scope tags), children (list of "
        "branch objects with the same shape)). Scope tags are short "
        "atomic labels (e.g. demand, cost, delivery). Every branch must "
        "have at least one scope tag. Sibling scopes must be disjoint "
        "and jointly cover the parent scope exactly.\n\n" + _JSON_ONLY,
        ("topic", "context", "dimensions", "existing_tree", "output_language"),
    )
)


def get_template(template_id: str) -> SkillTemplate:
    """Return a registered template, raising a clear error when unknown."""
    try:
        return TEMPLATES[template_id]
    except KeyError:
        known = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown skill template {template_id!r}. Known: {known}.") from None


def list_templates() -> list[SkillTemplate]:
    """All registered templates, in registry (insertion) order."""
    return list(TEMPLATES.values())


def _placeholders(text: str) -> set[str]:
    found: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(text):
        if field_name is None:
            continue
        if not _PLACEHOLDER_RE.match(field_name):
            raise ValueError(f"Invalid placeholder {{{field_name}}} in template text.")
        found.add(field_name)
    return found


def validate_registry() -> None:
    """Check every template's declared slots match its placeholders exactly."""
    for template in TEMPLATES.values():
        used = _placeholders(template.system_prompt) | _placeholders(template.user_template)
        declared = set(template.slots)
        if used != declared:
            raise ValueError(
                f"Template {template.id!r} slot mismatch: "
                f"declared={sorted(declared)} used={sorted(used)}."
            )


def render_template(
    template: SkillTemplate, inputs: dict[str, str]
) -> tuple[str, str]:
    """Render a template deterministically. Pure: same inputs, same output.

    Raises ``ValueError`` naming every missing slot. Extra inputs are
    ignored. Literal braces in template text use ``{{``/``}}`` escapes.
    """
    used = _placeholders(template.system_prompt) | _placeholders(template.user_template)
    missing = sorted(name for name in used if name not in inputs)
    if missing:
        raise ValueError(
            f"Template {template.id!r} missing inputs for slots: {', '.join(missing)}."
        )
    values = {name: str(inputs[name]) for name in used}
    return template.system_prompt.format_map(values), template.user_template.format_map(values)


validate_registry()

__all__ = [
    "DECISION_CRITERIA",
    "FRAMEWORK_INDEX",
    "LENS_BRIEFS",
    "LENS_QUESTIONS",
    "OPTION_MANDATES",
    "SkillTemplate",
    "TEMPLATES",
    "get_template",
    "list_templates",
    "render_template",
    "validate_registry",
]
