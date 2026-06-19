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
    assert "VALID" in result.stdout
    match = re.search(r"total=(\d+)", result.stdout)
    assert match, f"missing total=<value> in {result.stdout!r}"
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


def test_source_is_branchless():
    text = SOURCE.read_text(errors="replace")
    # The hot loop must no longer guard the accumulation with an `if`.
    # Accept the common branchless forms: predicate-multiply, ternary-as-value,
    # explicit mask, or a documented branchless intent.
    branchless_markers = [
        ">= threshold) *",
        ">= threshold ? ",
        "branchless",
        "& -",          # mask trick: (v >= t) producing an all-ones mask
        "__builtin_expect",
    ]
    assert any(m in text for m in branchless_markers), (
        "source should remove the data-dependent branch from the hot loop "
        "(use a branchless/predicated summation instead of `if (...) total += ...`)"
    )
