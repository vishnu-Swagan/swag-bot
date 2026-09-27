"""Errors from verification-gated skill learning."""

from __future__ import annotations

from swag_bot.errors import SwagError


class SkillLearningError(SwagError):
    """A run could not be distilled, or a candidate could not change state."""
