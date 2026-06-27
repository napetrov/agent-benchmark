#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/spin_fixed")
SOURCE = Path("/app/spin_fixed.cpp")
TIMEOUT = 60.0


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def _function_body(src, name):
    match = re.search(rf"\b{name}\s*\([^)]*\)\s*(?:const\s*)?\{{", src)
    assert match, f"missing {name}() implementation"
    start = match.end()
    depth = 1
    for pos in range(start, len(src)):
        if src[pos] == "{":
            depth += 1
        elif src[pos] == "}":
            depth -= 1
            if depth == 0:
                return src[start:pos]
    raise AssertionError(f"could not parse {name}() body")


def _run(threads, iters):
    cmd = [str(BINARY), str(threads), str(iters)]
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, (
        f"{cmd} exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    match = re.search(r"count=(\d+)", result.stdout)
    assert match, f"missing count=<value> in {result.stdout!r}"
    return int(match.group(1)), elapsed


def test_binary_exists():
    assert SOURCE.exists(), "write /app/spin_fixed.cpp"
    assert BINARY.exists(), "compile /app/spin_fixed"
    assert os.access(BINARY, os.X_OK), "/app/spin_fixed is not executable"


def test_mutual_exclusion_exact_total():
    # mutual exclusion must hold at several thread counts: no lost updates
    for threads, iters in [(2, 200000), (4, 200000), (8, 100000)]:
        total, _ = _run(threads, iters)
        assert total == threads * iters, (
            f"lost updates: threads={threads} iters={iters} got {total} expected {threads * iters}"
        )


def test_no_livelock_under_high_contention():
    # heavy oversubscription must still terminate well within the time limit.
    # This catches both livelock and an unbounded (uncapped) backoff that would
    # stall progress, without relying on a flaky speedup margin — the measured
    # TAS/TTAS/backoff ratio is too noisy on a CPU-pinned CI host to gate on.
    total, elapsed = _run(64, 60000)
    assert total == 64 * 60000
    assert elapsed < 30.0, f"high-contention run took {elapsed:.1f}s; possible livelock or uncapped backoff"


def test_source_keeps_ttas_read_spin():
    src = _strip_comments(SOURCE.read_text(errors="replace"))
    body = _function_body(src, "lock")
    load = re.search(r"\bwhile\s*\([^)]*\.load\s*\([^)]*\)[^)]*\)", body, re.S)
    acquire = re.search(r"\.(?:exchange|compare_exchange(?:_weak|_strong)?)\s*\(", body)
    assert load, "must keep the TTAS read-only spin (while on an atomic .load) "
    assert acquire, "still needs an atomic exchange/CAS to actually acquire the lock"
    assert load.start() < acquire.start(), "read-spin must precede the atomic acquire attempt"


def test_source_adds_capped_exponential_backoff():
    src = _strip_comments(SOURCE.read_text(errors="replace"))
    body = _function_body(src, "lock")

    # multiplicative growth: a shift (<<) or a multiply by 2 of the backoff value
    grows = re.search(r"<<\s*1\b", body) or re.search(r"\*\s*2\b", body) \
        or re.search(r"<<=", body) or re.search(r"\*=\s*2\b", body)
    assert grows, "backoff must grow multiplicatively (e.g. backoff <<= 1 or backoff *= 2)"

    # a cap that bounds the backoff (min/clamp/conditional against a max constant)
    capped = re.search(r"\b(?:min|clamp)\b", body) \
        or re.search(r"<\s*[A-Za-z0-9_]*[Mm][Aa][Xx]", body) \
        or re.search(r"[Mm][Aa][Xx][A-Za-z0-9_]*\s*[<>]", body) \
        or re.search(r"\?[^;]*:[^;]*;", body)  # ternary clamp like (b<CAP)?b<<1:CAP
    assert capped, "backoff must be capped to bound worst-case delay (min/clamp/conditional max)"

    # a CPU-relax / pause / yield body for the delay
    relax = re.search(r"_mm_pause|__builtin_ia32_pause|\bpause\b|this_thread::yield", src)
    assert relax, "backoff should spin on a relax/pause body (_mm_pause/pause/yield)"
