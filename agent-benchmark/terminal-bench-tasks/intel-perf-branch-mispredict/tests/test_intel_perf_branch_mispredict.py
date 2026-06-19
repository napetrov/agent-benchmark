#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BAD = Path("/app/branch_mispredict_bad")
BINARY = Path("/app/branch_mispredict_fixed")
SOURCE = Path("/app/branch_mispredict_fixed.cpp")
ARGS = ["20000000", "10"]
TIMEOUT = 30.0


def _run(cmd):
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, f"{cmd} exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    # Require VALID as a whole word at the start of the status line so that
    # "INVALID total=..." cannot satisfy the check.
    match = re.search(r"(?m)^VALID total=(\d+)\s*$", result.stdout)
    assert match, f"missing 'VALID total=<value>' line in {result.stdout!r}"
    return int(match.group(1)), elapsed


def _best_time(cmd, rounds=3):
    _run(cmd)  # warmup: absorb cold-cache and CPU-frequency-ramp effects before timing
    total = None
    elapsed = []
    for _ in range(rounds):
        total, seconds = _run(cmd)
        elapsed.append(seconds)
    return total, min(elapsed)


def test_binary_exists():
    assert SOURCE.exists(), "write /app/branch_mispredict_fixed.cpp"
    assert BINARY.exists(), "compile /app/branch_mispredict_fixed"
    assert os.access(BINARY, os.X_OK), "/app/branch_mispredict_fixed is not executable"


def test_correct_and_faster_than_branchy_baseline():
    bad_total, bad_time = _best_time([str(BAD), *ARGS])
    fixed_total, fixed_time = _best_time([str(BINARY), *ARGS])
    # Same data, same threshold, same arithmetic: the result must be identical.
    assert fixed_total == bad_total, (
        f"fixed total {fixed_total} must equal baseline total {bad_total}"
    )
    assert fixed_time < bad_time * 0.90, (
        f"expected branch-misprediction fix speedup; bad={bad_time:.4f}s fixed={fixed_time:.4f}s"
    )


def _strip_comments(src: str) -> str:
    # Remove // line comments and /* ... */ block comments so that keywords in
    # comments cannot satisfy the branchless check.
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


def test_source_is_branchless():
    code = _strip_comments(SOURCE.read_text(errors="replace"))
    # Require a concrete branchless arithmetic form in the (comment-free) source:
    # predicate-multiply, ternary-as-value, or an explicit mask trick.
    branchless_forms = [
        ">= threshold) *",
        ">= threshold ?",
        "& -",  # mask trick: (v >= t) producing an all-ones mask
    ]
    has_branchless_form = any(m in code for m in branchless_forms)
    # And reject any data-dependent `if (... >= threshold ...)` guard remaining in
    # the source, which is the branchy pattern the task asks to eliminate.
    has_branchy_threshold_if = (
        re.search(r"if\s*\([^)]*>=\s*threshold[^)]*\)", code) is not None
    )
    assert has_branchless_form and not has_branchy_threshold_if, (
        "source should remove the data-dependent branch from the hot loop "
        "(use a branchless/predicated summation instead of `if (...) total += ...`)"
    )
