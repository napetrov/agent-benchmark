#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/dense_fast")
SOURCE = Path("/app/dense_fast.cpp")
SERIAL = Path("/app/dense_serial")
PASSES = "240"
TIMEOUT = 30.0

# Deterministic single-thread throughput task: the oracle measures ~4.5x over
# the scalar baseline with negligible run-to-run variance, so a real speedup
# gate is safe. The floor is set well below the measured margin to stay green
# on slower CI hosts (see docs/difficulty-rubric.md trigger/gate guidance).
SPEEDUP_FLOOR = 1.8


def _run(cmd):
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, (
        f"{cmd} exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "VALID" in result.stdout
    match = re.search(r"dnn=([-+0-9.eE]+)", result.stdout)
    assert match, f"missing dnn=<value> in {result.stdout!r}"
    return float(match.group(1)), elapsed


def _best_time(cmd, rounds=3):
    _run(cmd)  # warmup: absorb cold-cache and CPU-frequency-ramp effects before timing
    values = []
    elapsed = []
    for _ in range(rounds):
        value, seconds = _run(cmd)
        values.append(value)
        elapsed.append(seconds)
    return values[-1], min(elapsed)


def test_binary_exists():
    assert SOURCE.exists(), "write /app/dense_fast.cpp"
    assert BINARY.exists(), "compile /app/dense_fast"
    assert os.access(BINARY, os.X_OK), "/app/dense_fast is not executable"


def test_result_matches_serial_and_is_faster():
    serial_value, serial_time = _best_time([str(SERIAL), PASSES])
    fast_value, fast_time = _best_time([str(BINARY), PASSES])
    tolerance = max(1e-4, abs(serial_value) * 1e-9)
    assert abs(serial_value - fast_value) <= tolerance, (
        f"dnn checksum mismatch: serial={serial_value} fast={fast_value}"
    )
    assert fast_time < serial_time / SPEEDUP_FLOOR, (
        f"expected at least {SPEEDUP_FLOOR}x speedup; "
        f"serial={serial_time:.4f}s fast={fast_time:.4f}s"
    )


def test_preserves_leaky_relu_activation():
    text = SOURCE.read_text(errors="replace")
    # The activation must survive the rewrite: a 0.01 leaky-ReLU slope on the
    # negative branch. Without it the checksum tolerance check would already
    # fail, but assert explicitly so a wrong-but-lucky variant is still caught.
    assert "0.01" in text, "leaky-ReLU activation (0.01f * sum) must be preserved"


def test_source_breaks_single_accumulator_pattern():
    text = SOURCE.read_text(errors="replace")
    uses_simd = bool(re.search(r"_mm_|_mm256_|__m128|__m256", text))
    accumulator_names = len(re.findall(r"\b(acc|sum|partial)[A-Za-z0-9_]*\b", text))
    assert uses_simd or accumulator_names >= 4, (
        "source should use SIMD intrinsics or multiple independent partial "
        "accumulators to break the loop-carried dependency"
    )
