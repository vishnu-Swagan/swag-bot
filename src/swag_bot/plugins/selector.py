"""Pick skills for a goal by keyword overlap.

No embeddings and no model calls. Scores use the skill name and the
description that was loaded at discovery time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from swag_bot.interfaces import SkillMeta

_STOP = frozenset(
    """
    a an the to for of and or when use with from in on at by into over
    me my this that these those please help user mentions about your it is
    be as if then than
    """.split()
)


def select_skills(skills: Sequence[SkillMeta], goal: str, *, limit: int = 5) -> list[SkillMeta]:
    """Return up to ``limit`` skills that match ``goal``, best first.

    An empty goal or a non-positive limit returns no skills. Skills with no
    token overlap are omitted.
    """
    if limit <= 0 or not goal.strip():
        return []
    ranked = [(score_skill(skill, goal), skill) for skill in skills]
    matched = [(score, skill) for score, skill in ranked if score > 0]
    matched.sort(key=lambda item: (-item[0], item[1].name))
    return [skill for _score, skill in matched[:limit]]


def score_skill(meta: SkillMeta, goal: str) -> int:
    """Higher means the skill description is a closer keyword match for ``goal``."""
    goal_tokens = _tokens(goal)
    if not goal_tokens:
        return 0
    name_tokens = set(_tokens(meta.name.replace("-", " ")))
    description_tokens = set(_tokens(meta.description))
    score = 0
    for token in goal_tokens:
        if token in name_tokens:
            score += 3
        if token in description_tokens:
            score += 2
    readable = meta.name.replace("-", " ")
    if readable and readable in goal.casefold():
        score += 5
    return score


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 1 and token not in _STOP
    ]
