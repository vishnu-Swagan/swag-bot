"""Constants for the run-bundle format.

The prose spec is ``docs/spec/run-bundle.md``. Evidence rows inside a bundle
use the Evidence Contract (``docs/spec/evidence-contract.md``) when that file
is present, and the same record names either way.
"""

from __future__ import annotations

SPEC_ID = "swag-run-bundle"
SPEC_VERSION = "1.0"

EVIDENCE_SPEC = "swag-evidence-contract"
EVIDENCE_VERSION = "1.0"

UNDO_ALIGNMENT = "swag-undo-snapshot"

# Bodies stored in the bundle, matching the evidence contract cap.
BLOB_CHAR_LIMIT = 2_000_000
PREVIEW_LIMIT = 400
DIFF_CHAR_LIMIT = 100_000

ARTIFACT_FILES = frozenset(
    {
        "plan.json",
        "action-log.jsonl",
        "summary.md",
        "run.jsonl",
    }
)
SKIP_TOP_DIRS = frozenset({".git", ".swag", "__pycache__", "bundle", "evidence"})
