"""Keyword skill selection."""

from __future__ import annotations

from swag_bot.interfaces import SkillMeta
from swag_bot.plugins.selector import select_skills

GITHUB = SkillMeta(
    name="github-issue-helper",
    description=(
        "Draft and triage GitHub issues. Use when the user mentions GitHub issues, "
        "bug reports, or pull request descriptions."
    ),
)
PDF = SkillMeta(
    name="pdf-processing",
    description=(
        "Extract text from PDF files. Use when the user mentions PDFs or portable documents."
    ),
)
NOTES = SkillMeta(
    name="notes",
    description="Take notes. Use when the user mentions notes or a scratch pad.",
)


def test_selects_github_skill_for_an_issue() -> None:
    chosen = select_skills([PDF, GITHUB, NOTES], "please triage this github issue about login")
    assert [skill.name for skill in chosen] == ["github-issue-helper"]


def test_selects_pdf_skill() -> None:
    chosen = select_skills([GITHUB, PDF], "extract text from the pdf")
    assert [skill.name for skill in chosen] == ["pdf-processing"]


def test_empty_goal_and_limit() -> None:
    assert select_skills([GITHUB], "   ") == []
    assert select_skills([GITHUB], "github issue", limit=0) == []


def test_limit_keeps_the_best_match() -> None:
    chosen = select_skills(
        [NOTES, GITHUB, PDF],
        "use the github issue helper, and also keep notes",
        limit=1,
    )
    assert len(chosen) == 1
    assert chosen[0].name == "github-issue-helper"
