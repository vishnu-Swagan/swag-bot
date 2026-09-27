"""Deterministic step checks used by the tiny scaffold.

These look at real tool results recorded by the executor. They do not replace
the evidence ledger. When a check cannot decide, it returns None and the
model verifier still runs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from swag_bot.core.scaffold import EarlyVerdict
from swag_bot.interfaces import Step, StepResult

_RUN = re.compile(r"\b(run|execute|python|pytest)\b", re.IGNORECASE)
_EXIT = re.compile(r"exit_code=(\d+)")


def deterministic_precheck(
    step: Step,
    result: StepResult,
    traces: Sequence[str],
) -> EarlyVerdict | None:
    """Pass or fail from tool results when the signal is unambiguous."""
    del result
    text = f"{step.title}\n{step.instruction}"
    wants_run = _RUN.search(text) is not None
    joined = "\n".join(traces)
    wrote = any(line.startswith("write_file:") for line in traces)
    ran = any(line.startswith("run_shell:") for line in traces)
    codes = [int(code) for code in _EXIT.findall(joined)]
    if codes and any(code != 0 for code in codes):
        return EarlyVerdict(False, f"a command exited {codes[-1]}", False)
    if wants_run and wrote and not ran:
        return EarlyVerdict(False, "the file was written but the step did not run it", False)
    if ran and codes and all(code == 0 for code in codes):
        return EarlyVerdict(True, "the command exited 0", False)
    return None
