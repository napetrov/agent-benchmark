#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/q29_fast")
SOURCE = Path("/app/q29_fast.cpp")
SERIAL = Path("/app/q29_serial")
PASSES = "6"
TIMEOUT = 60.0

# Deterministic single-thread workload: the rewrite removes ~89 of 90 passes
# over memory, so the speedup is large and stable. The floor is set well below
# the measured margin to stay green on slower CI hosts (see difficulty-rubric).
SPEEDUP_FLOOR = 1.8


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def _run(cmd):
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, (
        f"{cmd} exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "VALID" in result.stdout
    match = re.search(r"q29=(\d+)", result.stdout)
    assert match, f"missing q29=<value> in {result.stdout!r}"
    return int(match.group(1)), elapsed


def _best_time(cmd, rounds=3):
    _run(cmd)  # warmup: absorb cold-cache and CPU-frequency-ramp effects before timing
    value = None
    elapsed = []
    for _ in range(rounds):
        value, seconds = _run(cmd)
        elapsed.append(seconds)
    return value, min(elapsed)


def test_binary_exists():
    assert SOURCE.exists(), "write /app/q29_fast.cpp"
    assert BINARY.exists(), "compile /app/q29_fast"
    assert os.access(BINARY, os.X_OK), "/app/q29_fast is not executable"


def test_checksum_matches_serial_and_is_faster():
    serial_value, serial_time = _best_time([str(SERIAL), PASSES])
    fast_value, fast_time = _best_time([str(BINARY), PASSES])
    assert serial_value == fast_value, (
        f"q29 checksum mismatch: serial={serial_value} fast={fast_value}"
    )
    assert fast_time < serial_time / SPEEDUP_FLOOR, (
        f"expected at least {SPEEDUP_FLOOR}x speedup; "
        f"serial={serial_time:.4f}s fast={fast_time:.4f}s"
    )


def test_source_avoids_per_literal_materialization():
    src = _strip_comments(SOURCE.read_text(errors="replace"))
    # The fix derives the 90 sums algebraically from a single column pass; it
    # should NOT build a per-literal intermediate column. A second large buffer
    # the size of the input, written inside the per-column loop, is the smell.
    # Require evidence of the closed-form correction: a "k * n"/"k * N" style
    # term (SUM(c) + k*COUNT(c)).
    closed_form = re.search(r"\b[kK]\b\s*\*\s*\bn\b", src) \
        or re.search(r"\bn\b\s*\*\s*\b[kK]\b", src) \
        or re.search(r"\b[kK]\b\s*\*\s*\bN\b", src) \
        or re.search(r"COUNT", src, re.I)
    assert closed_form, (
        "optimized version should derive SUM(c+k) as SUM(c) + k*COUNT(c) rather "
        "than materializing each intermediate column"
    )
