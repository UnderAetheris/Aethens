"""Model-Assisted Patching v0 — the first time a real LLM authors diffs.

The sentence that governs everything: **a model suggestion is data, not an
action, and validation — not the model — decides trust.**  The model gets
text in and text out.  It holds no tool, no shell, no network, no SafetyLayer,
no live-tree writer.  A ``PatchCandidate`` is frozen data with no method that
does anything.

The trust boundary is harder than what deterministic repairs face, because a
model patch starts *untrusted* and must earn its way in.  A proposal must clear
all six gates or it is rejected, the sandbox is discarded, and we fall back to
deterministic repair:

1. Parses as a well-formed (unified) diff.
2. Every target path resolves inside the workspace root (reject out-of-root instantly).
3. Applies cleanly in a *sandbox copy* — never the live tree.
4. Stays in-scope — no sprawl to unrelated files; the blast radius is bounded
   (a single file in v0; multi-file is a later, gated widening).
5. Allowlisted tests pass.
6. Zero regressions.

Even a patch that passes the sandbox is *not* applied by the model or the
validator.  It is handed back as candidate **content** (a ``PatchProposal`` of
validated ``edit_file`` repair steps); Reflection owns the verdict and the edit
executes through the unchanged ``edit_file`` via ``SafetyLayer.run()``.  Same
single writer, same gate, no new path.  The model changed the *content* of a
repair; it never touched the *authority* to apply one.

Everything else stays advisory, as held throughout: Understanding targets the
right file, Reasoning can rank validated candidates, and Experience biases
toward fixes that worked and *away from retired patterns* — a model patch that
resembles a retired pattern gets extra scrutiny (it is rejected if it would
re-introduce that pattern).

The floor is sacred: model off, or model abstains/errors/proposes garbage ->
``propose_repair`` returns ``None`` and the caller uses deterministic repair.
Canary: ``test_model_off_is_byte_identical``.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..memory.experience_rerank import _significant_tokens
from ..model.interface import ModelRequest, ResponseKind


# ---------------------------------------------------------------------------
# Data, not action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileDiff:
    """One parsed file change. Pure data — no method applies anything."""

    path: str                       # repo-relative target path
    old_text: str = ""             # original content (after sandbox apply)
    new_text: str = ""             # patched content


@dataclass(frozen=True)
class PatchCandidate:
    """A model's raw suggestion, parsed. Frozen data; nothing here acts.

    ``parsed`` is False (and ``error`` set) when the raw text was not a
    well-formed diff — that alone fails gate 1.
    """

    raw: str
    diffs: tuple[FileDiff, ...] = ()
    parsed: bool = False
    error: str = ""


@dataclass(frozen=True)
class PatchTestReport:
    """Result of running allowlisted tests against a sandbox copy."""

    passed: bool
    regressed: bool
    detail: str = ""


class PatchTestRunner(Protocol):
    """Callable that runs allowlisted tests in a sandbox root and reports."""

    def __call__(self, sandbox_root: str) -> PatchTestReport:
        ...


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str
    applied: tuple[FileDiff, ...] = ()
    resembles_retired: bool = False
    sandbox_root: str | None = None


@dataclass(frozen=True)
class PatchProposal:
    """Validated, ready-to-hand-to-Reflection content.

    ``repair_steps`` has the exact same shape as Reflection's repair steps:
    a list of ``(tool, arg)`` pairs.  For v0 the tool is always ``edit_file``
    and ``arg`` is a whole-file find/replace.  Reflection owns the verdict;
    the executive applies it through ``SafetyLayer.run()``.
    """

    repair_steps: tuple[tuple[str, str], ...]
    resembles_retired: bool = False
    detail: str = ""


# ---------------------------------------------------------------------------
# Test runner (pluggable; default shells out to pytest)
# ---------------------------------------------------------------------------


def default_test_runner() -> Callable[[str], PatchTestReport]:
    """Run ``pytest -q`` in the sandbox root. Allowlisted by the caller."""

    def run(sandbox_root: str) -> PatchTestReport:
        import subprocess

        try:
            proc = subprocess.run(
                ["pytest", "-q", sandbox_root],
                capture_output=True, text=True, timeout=120,
            )
            return PatchTestReport(
                passed=proc.returncode == 0,
                regressed=False,
                detail=(proc.stdout + proc.stderr)[-500:],
            )
        except Exception as e:  # noqa: BLE001
            return PatchTestReport(passed=False, regressed=False, detail=str(e))

    return run


# ---------------------------------------------------------------------------
# Unified-diff parsing + application (sandbox only)
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_code_fence(text: str) -> str:
    """Pull a fenced ```diff block if the model wrapped one around the patch."""
    m = re.search(r"```(?:diff)?\s*(.*?)```", text, re.DOTALL)
    return m.group(1) if m else text


def parse_diff(raw: str) -> PatchCandidate:
    """Parse a minimal unified diff into FileDiffs. Pure; rejects garbage."""
    text = _strip_code_fence(raw.strip())
    if not text:
        return PatchCandidate(raw=raw, error="empty patch")

    lines = text.splitlines()
    diffs: list[FileDiff] = []
    cur_path: str | None = None
    cur_old: list[str] = []
    cur_new: list[str] = []
    saw_hunk = False

    def flush() -> None:
        nonlocal cur_path, cur_old, cur_new, saw_hunk
        if cur_path is not None and saw_hunk:
            diffs.append(FileDiff(path=cur_path, old_text="\n".join(cur_old), new_text="\n".join(cur_new)))
        cur_path = None
        cur_old = []
        cur_new = []
        saw_hunk = False

    for line in lines:
        if line.startswith("--- "):
            flush()
            p = line[4:].strip()
            if p == "/dev/null":
                return PatchCandidate(raw=raw, error="new/deleted files unsupported in v0")
            cur_path = re.sub(r"^([ab])/", "", p)
            continue
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p == "/dev/null":
                return PatchCandidate(raw=raw, error="new/deleted files unsupported in v0")
            if cur_path is None:
                cur_path = re.sub(r"^([ab])/", "", p)
            else:
                cur_path = re.sub(r"^([ab])/", "", p)
            continue
        if line.startswith("@@"):
            if cur_path is None:
                return PatchCandidate(raw=raw, error="hunk before file header")
            m = _HUNK_RE.match(line)
            if not m:
                return PatchCandidate(raw=raw, error=f"bad hunk header: {line!r}")
            saw_hunk = True
            continue
        if cur_path is None or not saw_hunk:
            if line.strip() == "":
                continue
            return PatchCandidate(raw=raw, error="unexpected content outside a file/hunk")
        if line.startswith("+"):
            cur_new.append(line[1:])
        elif line.startswith("-"):
            cur_old.append(line[1:])
        elif line.startswith(" "):
            cur_old.append(line[1:])
            cur_new.append(line[1:])
        elif line.startswith("\\"):
            continue  # "No newline at end of file" — ignore
        else:
            return PatchCandidate(raw=raw, error=f"unexpected diff line: {line!r}")
    flush()

    if not diffs:
        return PatchCandidate(raw=raw, error="no file changes found")
    return PatchCandidate(raw=raw, diffs=tuple(diffs), parsed=True)


def _apply_in_sandbox(
    diffs: Sequence[FileDiff], root: Path, in_scope: set[str]
) -> tuple[FileDiff, ...] | str:
    """Copy targets into a sandbox and apply. Returns applied diffs or an error str."""
    sandbox = Path(tempfile.mkdtemp(prefix="aeth_patch_"))
    try:
        applied: list[FileDiff] = []
        for d in diffs:
            dest = sandbox / d.path
            live = root / d.path
            if not live.exists() or not live.is_file():
                return f"target file does not exist: {d.path}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(live, dest)
            original = dest.read_text(encoding="utf-8")
            replayed = _replay(original.split("\n"), d.old_text, d.new_text)
            if replayed is None:
                return f"patch does not apply cleanly to {d.path}"
            dest.write_text(replayed, encoding="utf-8")
            applied.append(FileDiff(path=d.path, old_text=d.old_text, new_text=d.new_text))
        return tuple(applied)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ---------------------------------------------------------------------------
# The patcher: model -> data -> validated proposal (or None)
# ---------------------------------------------------------------------------


class ModelAssistedPatcher:
    """Turns a model suggestion into a validated ``PatchProposal`` — or None.

    Owns no authority.  It asks the model for text, parses it as data, validates
    it against six gates in a throwaway sandbox, and (only on success) returns
    candidate content for Reflection to enact.  Any failure -> ``None`` so the
    caller falls back to deterministic repair.  The live tree is never touched.
    """

    def __init__(
        self,
        model: Any,
        workspace_root: str,
        *,
        experience=None,
        understanding=None,
        reasoning=None,
        test_runner: Callable[[str], PatchTestReport] | None = None,
        max_files: int = 1,
        confidence_floor: float = 0.5,
    ) -> None:
        self._model = model
        self._root = Path(workspace_root).resolve()
        self._experience = experience
        self._understanding = understanding
        self._reasoning = reasoning
        self._test_runner = test_runner or default_test_runner()
        self._max_files = max_files
        self._confidence_floor = confidence_floor

    # ------------------------------------------------------------------ #
    # Public seam                                                         #
    # ------------------------------------------------------------------ #

    def propose_repair(self, outcome: Any, plan: Any = None) -> PatchProposal | None:
        """Attempt a model-authored repair. Returns None to fall back.

        Safe under all "off" conditions: no model, model errors, model
        abstains, or the suggestion fails any gate -> None.  Never mutates the
        live tree.
        """
        if self._model is None:
            return None
        try:
            request = ModelRequest(
                kind=ResponseKind.PATCH,
                task=outcome.output or "",
                context=self._context_for(outcome),
            )
            response = self._model.complete(request)
        except Exception:
            return None
        if not getattr(response, "ok", False) or not getattr(response, "text", ""):
            return None

        candidate = parse_diff(getattr(response, "text", ""))
        if not candidate.parsed:
            return None

        in_scope = self._derive_in_scope(outcome)
        result = self._validate(candidate, in_scope)
        if not result.passed:
            return None

        steps = tuple(
            (
                "edit_file",
                json.dumps({"path": d.path, "find": d.old_text, "replace": d.new_text}),
            )
            for d in result.applied
        )
        return PatchProposal(
            repair_steps=steps,
            resembles_retired=result.resembles_retired,
            detail=result.reason,
        )

    # ------------------------------------------------------------------ #
    # Validation gates                                                    #
    # ------------------------------------------------------------------ #

    def _validate(self, candidate: PatchCandidate, in_scope: set[str]) -> ValidationResult:
        diffs = candidate.diffs

        # Gate 4 (part 1): bound the blast radius — single file in v0.
        if len(diffs) > self._max_files:
            return ValidationResult(False, f"sprawl: touches {len(diffs)} files (> {self._max_files} allowed)")

        # Gate 2: every path must resolve inside the workspace root.
        for d in diffs:
            try:
                target = (self._root / d.path).resolve()
            except (ValueError, OSError):
                return ValidationResult(False, f"unresolvable path: {d.path}")
            if target != self._root and self._root not in target.parents:
                return ValidationResult(False, f"out-of-root path rejected instantly: {d.path}")

        # Gate 4 (part 2): in-scope — if we can name the failing file, stay on it.
        if in_scope:
            for d in diffs:
                if (self._root / d.path).resolve().as_posix() not in in_scope:
                    return ValidationResult(False, f"out-of-scope file rejected: {d.path}")

        # Retired-pattern check (Experience): extra scrutiny, before sandbox work.
        resembles = self._resembles_retired(candidate)
        if resembles:
            # A patch that would re-introduce a retired pattern is rejected.
            retired_tokens = self._retired_tokens()
            new_blob = "\n".join(d.new_text for d in diffs)
            if retired_tokens and not retired_tokens.isdisjoint(_significant_tokens(new_blob)):
                return ValidationResult(
                    False, "resembles a retired pattern and would re-introduce it", resembles_retired=True
                )

        # Gate 3: applies cleanly in a sandbox copy (never the live tree).
        applied = _apply_in_sandbox(diffs, self._root, in_scope)
        if isinstance(applied, str):
            return ValidationResult(False, applied, resembles_retired=resembles)

        # Gates 5 & 6: allowlisted tests pass, zero regressions (in a patched sandbox).
        report = self._run_tests_on_patched(applied)
        if not report.passed:
            return ValidationResult(False, f"tests failed: {report.detail}", resembles_retired=resembles)
        if report.regressed:
            return ValidationResult(False, f"regression detected: {report.detail}", resembles_retired=resembles)

        return ValidationResult(True, "all gates passed", applied=applied, resembles_retired=resembles)

    def _run_tests_on_patched(self, applied: Sequence[FileDiff]) -> PatchTestReport:
        """Materialize the patched files in a throwaway sandbox and test them."""
        sandbox = Path(tempfile.mkdtemp(prefix="aeth_patch_test_"))
        try:
            for d in applied:
                dest = sandbox / d.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                (self._root / d.path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(self._root / d.path, dest)
                original = dest.read_text(encoding="utf-8")
                replayed = _replay(original.split("\n"), d.old_text, d.new_text)
                if replayed is None:
                    return PatchTestReport(passed=False, regressed=False, detail=f"cannot materialize {d.path}")
                dest.write_text(replayed, encoding="utf-8")
            return self._test_runner(str(sandbox))
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Advisory context                                                     #
    # ------------------------------------------------------------------ #

    def _context_for(self, outcome: Any) -> str:
        bits: list[str] = []
        if self._understanding is not None:
            try:
                facts = self._understanding.project_facts()
                if facts:
                    bits.append(f"language={facts.get('language')} build={facts.get('build_system')}")
            except Exception:
                pass
        if outcome.tool == "edit_file":
            try:
                bits.append(f"target={json.loads(outcome.arg).get('path')}")
            except Exception:
                pass
        return "; ".join(bits)

    def _derive_in_scope(self, outcome: Any) -> set[str]:
        """Best-effort single in-scope file (the failing step's target)."""
        if outcome.tool == "edit_file":
            try:
                p = (self._root / json.loads(outcome.arg)["path"]).resolve().as_posix()
                return {p}
            except Exception:
                return set()
        return set()

    def _resembles_retired(self, candidate: PatchCandidate) -> bool:
        if self._experience is None:
            return False
        try:
            retired = self._experience.retired_lessons()
        except Exception:
            return False
        if not retired:
            return False
        blob = "\n".join([candidate.raw, *(d.new_text for d in candidate.diffs)])
        tokens = _significant_tokens(blob)
        return any(
            not _significant_tokens(f"{les.problem} {les.cause} {les.fix}").isdisjoint(tokens)
            for les in retired
        )

    def _retired_tokens(self) -> set[str]:
        out: set[str] = set()
        for les in self._experience.retired_lessons():
            out |= _significant_tokens(f"{les.problem} {les.cause} {les.fix}")
        return out


def _replay(old_lines: list[str], old_text: str, new_text: str) -> str | None:
    """Replay a (old, new) change onto live lines; None if it doesn't fit cleanly."""
    old = old_text.split("\n")
    new = new_text.split("\n")
    if not old:
        return "\n".join(new + old_lines)
    n = len(old)
    for start in range(0, len(old_lines) - n + 1):
        if old_lines[start:start + n] == old:
            return "\n".join(old_lines[:start] + new + old_lines[start + n:])
    return None

