#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/spin_fixed")
SOURCE = Path("/app/spin_fixed.cpp")
# Subprocess hard-kill budget. Kept above the no-livelock assertion bound (60 s,
# see test_no_livelock_under_high_contention) so a genuinely hung lock reaches
# that assertion — and its "possible livelock" message — instead of dying here
# with an unhandled TimeoutExpired.
TIMEOUT = 90.0


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
    assert result.returncode == 0, f"{cmd} exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
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
    # heavy oversubscription must still terminate well within the time limit;
    # this catches livelock/deadlock without relying on a flaky speedup margin.
    #
    # The bound is deliberately generous: 64 threads on a CPU-capped container
    # (the harness runs with --cpus 4) is ~16x oversubscribed, so absolute
    # wall-clock varies widely with host load. A correct TTAS lock finishes in a
    # few seconds; a livelocked/deadlocked one does not terminate at all. The old
    # 30 s bound flaked on loaded hosts (observed 30.9-41.4 s for CORRECT locks) —
    # it was measuring throughput, not liveness. 60 s cleanly separates
    # "terminates" from "hung" without the false negatives.
    total, elapsed = _run(64, 60000)
    assert total == 64 * 60000
    assert elapsed < 60.0, f"high-contention run took {elapsed:.1f}s; possible livelock"


def test_source_uses_test_and_test_and_set():
    src = _strip_comments(SOURCE.read_text(errors="replace"))
    body = _function_body(src, "lock")
    # must spin on an ordinary load (.load(...)) before attempting the atomic
    # exchange/compare_exchange — the defining property of TTAS
    load = re.search(r"\bwhile\s*\([^)]*\.load\s*\([^)]*\)[^)]*\)", body, re.S)
    acquire = re.search(r"\.(?:exchange|compare_exchange(?:_weak|_strong)?)\s*\(", body)
    has_read_spin = bool(load)
    has_atomic_acquire = bool(acquire)
    # The defining property of TTAS is that a waiter spins on an ordinary read
    # of the lock and only issues the atomic acquire when the flag looks free —
    # i.e. BOTH a load-spin loop and an atomic acquire must be present. A bare
    # Test-and-Set has no read-spin at all and is rejected by has_read_spin.
    #
    # We deliberately do NOT require the load-spin to appear *textually before*
    # the acquire. The "try-first" TTAS variant — attempt the atomic exchange
    # once, then fall back to the read-spin loop on failure — is a legitimate,
    # lower-latency TTAS (it skips the read on an uncontended acquire) and puts
    # the exchange first. Requiring load-before-exchange wrongly failed that
    # correct form. Both loop orderings keep the read-spin off the hot path
    # under contention, which is the property that matters.
    assert has_read_spin, "TTAS must spin on an ordinary read (atomic load) before re-attempting the exchange"
    assert has_atomic_acquire, "TTAS still needs an atomic exchange/CAS to actually acquire the lock"
