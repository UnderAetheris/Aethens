"""Deterministic classification of test/command output.

No model.  Pure string/pattern matching.  The output (FailureKind) is
meant to ride in a StepOutcome so Reflection can key off it.
"""
from __future__ import annotations

from enum import Enum


class FailureKind(str, Enum):
    SYNTAX_ERROR = "syntax_error"
    ASSERTION_FAILURE = "assertion_failure"
    MISSING_IMPORT = "missing_import"
    COMMAND_NOT_FOUND = "command_not_found"
    UNSAFE_BLOCKED = "unsafe_blocked"
    UNKNOWN = "unknown"


class FailureParser:
    """Classify tool output into a FailureKind."""

    def classify(self, output: str, safety_blocked: bool) -> FailureKind:
        if safety_blocked:
            return FailureKind.UNSAFE_BLOCKED
        low = output.lower()
        if "syntaxerror" in low:
            return FailureKind.SYNTAX_ERROR
        if "modulenotfounderror" in low or "importerror" in low:
            return FailureKind.MISSING_IMPORT
        if "assertionerror" in low or "assert" in low:
            return FailureKind.ASSERTION_FAILURE
        if "command not found" in low or "no such file" in low:
            return FailureKind.COMMAND_NOT_FOUND
        return FailureKind.UNKNOWN
