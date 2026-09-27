"""Cheap per-step uncertainty, and the question to ask when it is high.

Signals, in the order they are cheap to collect:

- ``ambiguous_goal``: the goal does not name a target, or it names two.
- ``low_confidence_output``: the model hedges, or it reports a low confidence.
- ``self_consistency``: extra samples of the same question disagree.
- ``verifier_disagreement``: checks of the same step disagree.
- ``retries``: the step is already on a repeat attempt.

No signal is an extra model call except self-consistency, and that one stays
off unless ``samples`` is raised. A single local model still produces a score
from the other four. The score is not a conformal guarantee. :func:`suggest_threshold`
is a quantile helper for a later labeled set, in the spirit of KnowNo, not a
proof that the cutoff has a coverage guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_VAGUE_PHRASES = (
    "clean this up",
    "clean it up",
    "fix it",
    "fix this",
    "fix the bug",
    "make it better",
    "make this better",
    "handle this",
    "handle it",
    "do it",
    "do this",
    "do something",
    "improve it",
    "update it",
    "deal with it",
    "take care of it",
    "sort it out",
    "figure it out",
    "as needed",
)
_VAGUE_WORDS = frozenset({"it", "this", "that", "something", "stuff", "things", "whatever"})
_CONCRETE = re.compile(
    r"[\w.-]+\.(?:txt|md|py|json|toml|ya?ml|csv|html|css|rs|go|ts|tsx|jsx)\b"
    r"|[/\\][\w.-]+"
    r"|\b(?:file|files|directory|folder|path|paths|report|reports|test|tests)\b",
    re.IGNORECASE,
)
_OR = re.compile(r"\s+or\s+", re.IGNORECASE)
# A period ends the hedge only when it ends the sentence, so "report.md" stays intact.
_HEDGE_TAIL = r"(?:(?!\.(?:\s|$)).){0,160}"
_HEDGES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(rf"i(?:'m| am) not sure\b{_HEDGE_TAIL}", re.IGNORECASE), 0.84),
    (re.compile(rf"i do(?:n't| not) know\b{_HEDGE_TAIL}", re.IGNORECASE), 0.86),
    (re.compile(r"\b(?:uncertain|unsure|unclear)\b", re.IGNORECASE), 0.72),
    (re.compile(r"\b(?:maybe|perhaps|might)\b", re.IGNORECASE), 0.5),
)
_CONFIDENCE = re.compile(
    r"""['"]?confidence['"]?\s*[:=]\s*(0?\.\d+|1(?:\.0+)?|\d{1,3}\s*%)""",
    re.IGNORECASE,
)
_WEIGHTS = {
    "ambiguous_goal": 1.0,
    "low_confidence_output": 1.0,
    "self_consistency": 1.3,
    "verifier_disagreement": 1.3,
    "retries": 0.8,
}
_QUESTION_PRIORITY = (
    "verifier_disagreement",
    "self_consistency",
    "ambiguous_goal",
    "low_confidence_output",
    "retries",
)
# Pairs at least this far apart count as a disagreement. Identical samples
# from a deterministic local model stay under it and add nothing.
_DISAGREE_AT = 0.34


@dataclass(frozen=True)
class Signal:
    """One cheap clue. ``uncertainty`` is between 0 and 1."""

    name: str
    uncertainty: float
    detail: str


@dataclass(frozen=True)
class UncertaintyEstimate:
    """Combined score for one step, plus a question when it should escalate."""

    uncertainty: float
    confidence: float
    signals: tuple[Signal, ...]
    question: str
    should_escalate: bool


def estimate_uncertainty(
    *,
    goal: str,
    step_title: str,
    attempt: int = 1,
    observation: str = "",
    samples: Sequence[str] = (),
    verdicts: Sequence[tuple[bool, str]] = (),
    threshold: float = 0.6,
    clarified: bool = False,
) -> UncertaintyEstimate:
    """Score ``goal`` and the step. Escalate when the score is at or above ``threshold``.

    Missing inputs are skipped, not treated as zero. A step with no signals
    does not escalate, even when ``threshold`` is 0.
    """
    signals: list[Signal] = []
    if not clarified:
        ambiguous = ambiguous_goal_signal(goal)
        if ambiguous is not None:
            signals.append(ambiguous)
    low = low_confidence_signal(observation, samples)
    if low is not None:
        signals.append(low)
    consistent = self_consistency_signal(samples)
    if consistent is not None:
        signals.append(consistent)
    disagreed = verifier_disagreement_signal(verdicts)
    if disagreed is not None:
        signals.append(disagreed)
    retried = retry_signal(attempt, verdicts)
    if retried is not None:
        signals.append(retried)

    uncertainty = _combine(signals)
    confidence = _clamp(1.0 - uncertainty)
    question = ""
    escalate = bool(signals) and uncertainty >= threshold
    if escalate:
        question = _question(signals, goal=goal, step_title=step_title, attempt=attempt)
    return UncertaintyEstimate(
        uncertainty=uncertainty,
        confidence=confidence,
        signals=tuple(signals),
        question=question,
        should_escalate=escalate,
    )


def ambiguous_goal_signal(goal: str) -> Signal | None:
    """Fire when the goal names two actions, or names no target."""
    text = " ".join(goal.split())
    if not text:
        return None
    alternatives = _alternatives(text)
    if alternatives is not None:
        left, right = alternatives
        return Signal("ambiguous_goal", 0.78, f"{left} || {right}")
    if _concrete(text):
        return None
    normalized = text.casefold()
    if any(phrase in normalized for phrase in _VAGUE_PHRASES):
        return Signal("ambiguous_goal", 0.84, text)
    words = re.findall(r"[a-z0-9']+", normalized)
    if len(words) <= 4 and any(word in _VAGUE_WORDS for word in words):
        return Signal("ambiguous_goal", 0.8, text)
    return None


def low_confidence_signal(observation: str, samples: Sequence[str] = ()) -> Signal | None:
    """Fire on hedge language or an explicit confidence below 1."""
    chunks = [observation, *samples]
    best: Signal | None = None
    for chunk in chunks:
        found = _hedge(chunk)
        if found is None:
            continue
        if best is None or found.uncertainty > best.uncertainty:
            best = found
    return best


def self_consistency_signal(samples: Sequence[str]) -> Signal | None:
    """Fire when two or more samples of the same question disagree.

    ``uncertainty`` is ``1 - jaccard`` of the least similar pair. Samples that
    mostly overlap are dropped so a deterministic model does not escalate.
    """
    cleaned = [" ".join(sample.split()) for sample in samples if sample.strip()]
    if len(cleaned) < 2:
        return None
    worst = 0.0
    pair = (cleaned[0], cleaned[1])
    for index, left in enumerate(cleaned):
        for right in cleaned[index + 1 :]:
            distance = 1.0 - _jaccard(left, right)
            if distance > worst:
                worst = distance
                pair = (left, right)
    if worst < _DISAGREE_AT:
        return None
    detail = f"{_clip(pair[0], 120)} || {_clip(pair[1], 120)}"
    return Signal("self_consistency", _clamp(worst), detail)


def verifier_disagreement_signal(verdicts: Sequence[tuple[bool, str]]) -> Signal | None:
    """Fire when the same step was both accepted and rejected, or the reason hedges."""
    if not verdicts:
        return None
    flags = [passed for passed, _reason in verdicts]
    reasons = "; ".join(reason.strip() for _passed, reason in verdicts if reason.strip())
    if any(flags) and not all(flags):
        return Signal("verifier_disagreement", 0.9, reasons or "pass and fail")
    hedged = _hedge(reasons)
    if hedged is not None:
        return Signal("verifier_disagreement", max(0.7, hedged.uncertainty), reasons)
    return None


def retry_signal(attempt: int, verdicts: Sequence[tuple[bool, str]]) -> Signal | None:
    """Fire once a step is being tried again. The first attempt adds nothing."""
    if attempt < 2:
        return None
    score = 0.66 if attempt == 2 else 0.8 if attempt == 3 else 0.9
    reason = ""
    if verdicts:
        reason = verdicts[-1][1].strip()
    detail = reason or f"attempt {attempt}"
    return Signal("retries", score, detail)


def suggest_threshold(
    uncertainties_on_wrong_steps: Sequence[float],
    *,
    alpha: float = 0.1,
) -> float:
    """Pick a cutoff from uncertainty scores of steps that were wrong.

    Sorts the scores and returns the one at quantile ``alpha``. Escalating at
    that cutoff would have caught about ``1 - alpha`` of this labeled sample.
    This is not a conformal guarantee: the next run can look different, and an
    empty sample returns 0.6 (the default). ``alpha`` is clamped to ``[0, 1]``.
    """
    scores = [_clamp(score) for score in uncertainties_on_wrong_steps]
    if not scores:
        return 0.6
    bounded = min(1.0, max(0.0, alpha))
    ordered = sorted(scores)
    index = min(len(ordered) - 1, int(bounded * (len(ordered) - 1)))
    return ordered[index]


def _question(
    signals: Sequence[Signal],
    *,
    goal: str,
    step_title: str,
    attempt: int,
) -> str:
    chosen = _leading(signals)
    title = step_title.strip() or "this step"
    if chosen.name == "ambiguous_goal" and " || " in chosen.detail:
        left, right = chosen.detail.split(" || ", 1)
        return (
            f"The goal can mean two different actions: '{left}' or '{right}'. "
            f"Which one should step '{title}' do?"
        )
    if chosen.name == "ambiguous_goal":
        shown = " ".join(goal.split())
        return (
            f"The goal '{shown}' does not say which paths step '{title}' may change, "
            "or whether deleting is allowed. Which paths should I touch, "
            "and what should I leave alone?"
        )
    if chosen.name == "self_consistency" and " || " in chosen.detail:
        left, right = chosen.detail.split(" || ", 1)
        return (
            f"Step '{title}' has two disagreeing readings. "
            f"One is: '{left}'. The other is: '{right}'. Which one should I follow?"
        )
    if chosen.name == "verifier_disagreement":
        return (
            f"The checker disagreed on step '{title}'. "
            f"Reasons: '{_clip(chosen.detail, 200)}'. Which outcome should I treat as done?"
        )
    if chosen.name == "low_confidence_output":
        return (
            f"Step '{title}' produced an unsure result ('{_clip(chosen.detail, 180)}'). "
            f"What should I do with that step?"
        )
    if chosen.name == "retries":
        failures = max(1, attempt - 1)
        return (
            f"Step '{title}' has already failed {failures} time(s). "
            f"The last check said: '{_clip(chosen.detail, 160)}'. "
            f"What should change before I try again?"
        )
    return (
        f"Step '{title}' looks uncertain ({chosen.name}: '{_clip(chosen.detail, 160)}'). "
        f"What should I do next?"
    )


def _leading(signals: Sequence[Signal]) -> Signal:
    def sort_key(signal: Signal) -> tuple[float, int]:
        try:
            rank = _QUESTION_PRIORITY.index(signal.name)
        except ValueError:
            rank = len(_QUESTION_PRIORITY)
        return (-signal.uncertainty, rank)

    return min(signals, key=sort_key)


def _combine(signals: Sequence[Signal]) -> float:
    if not signals:
        return 0.0
    weight = 0.0
    total = 0.0
    for signal in signals:
        factor = _WEIGHTS.get(signal.name, 1.0)
        weight += factor
        total += signal.uncertainty * factor
    if weight <= 0:
        return 0.0
    return _clamp(total / weight)


def _alternatives(text: str) -> tuple[str, str] | None:
    match = _OR.search(text)
    if match is None:
        return None
    left = text[: match.start()].strip(" .,;:")
    right = text[match.end() :].strip(" .,;:")
    if len(left.split()) < 3 or len(right.split()) < 2:
        return None
    return left, right


def _concrete(text: str) -> bool:
    return _CONCRETE.search(text) is not None


def _hedge(text: str) -> Signal | None:
    if not text.strip():
        return None
    best_score = 0.0
    best_detail = ""
    for pattern, score in _HEDGES:
        match = pattern.search(text)
        if match is not None and score > best_score:
            best_score = score
            best_detail = " ".join(match.group(0).split())
    explicit = _explicit_confidence(text)
    if explicit is not None and explicit[0] > best_score:
        best_score, best_detail = explicit
    if best_score <= 0:
        return None
    return Signal("low_confidence_output", _clamp(best_score), best_detail or text.strip())


def _explicit_confidence(text: str) -> tuple[float, str] | None:
    match = _CONFIDENCE.search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    if raw.endswith("%"):
        number = float(raw[:-1].strip()) / 100.0
    else:
        number = float(raw)
    if number > 1.0:
        number = number / 100.0
    uncertainty = _clamp(1.0 - number)
    if uncertainty < _DISAGREE_AT:
        return None
    return uncertainty, " ".join(match.group(0).split())


def _jaccard(left: str, right: str) -> float:
    a = set(re.findall(r"[a-z0-9]+", left.casefold()))
    b = set(re.findall(r"[a-z0-9]+", right.casefold()))
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _clip(text: str, limit: int) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
