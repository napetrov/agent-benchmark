#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/crit_fixed")
SOURCE = Path("/app/crit_fixed.cpp")
TIMEOUT = 60.0
MASK64 = (1 << 64) - 1


def _compute(i):
    # mirrors Accumulator::compute() in the reference: a pure function of the
    # index, so the verifier can derive the expected total independently rather
    # than trusting whatever the binary prints.
    acc = i & MASK64
    for _ in range(64):
        acc = (acc * 6364136223846793005 + 1442695040888963407) & MASK64
        acc ^= acc >> 29
    return acc & MASK64


def _expected_total(threads, iters):
    total = 0
    for i in range(threads * iters):
        total = (total + _compute(i)) & MASK64
    return total


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
    match = re.search(r"total=(\d+)", result.stdout)
    assert match, f"missing total=<value> in {result.stdout!r}"
    return int(match.group(1)), elapsed


def test_binary_exists():
    assert SOURCE.exists(), "write /app/crit_fixed.cpp"
    assert BINARY.exists(), "compile /app/crit_fixed"
    assert os.access(BINARY, os.X_OK), "/app/crit_fixed is not executable"


def test_result_unchanged_at_several_thread_counts():
    # the fix must not change the computed total. Compare each run against an
    # independent Python reference (compute() is order-independent over a
    # commutative add), so a stub that prints a constant total cannot pass.
    for threads, iters in [(2, 100000), (4, 100000), (8, 50000)]:
        total, _ = _run(threads, iters)
        assert total == _expected_total(threads, iters), (
            f"wrong total at threads={threads} iters={iters}: got {total}"
        )
    # at equal element counts (threads*iters), the total must match
    a, _ = _run(4, 100000)
    b, _ = _run(8, 50000)  # same 400000 elements
    assert a == b, f"total depends on thread count ({a} vs {b}); reference sum broken"


def test_no_stall_under_high_contention():
    # heavy oversubscription must terminate well within the time limit. With the
    # critical section shrunk this is fast; a regression that re-bloats the lock
    # would slow it down. We avoid a strict speedup gate (CPU-pinned CI timing is
    # noisy) and only assert progress / no deadlock.
    total, elapsed = _run(64, 30000)
    assert total > 0
    assert elapsed < 30.0, f"high-contention run took {elapsed:.1f}s; critical section likely still bloated"


def test_compute_hoisted_out_of_critical_section():
    src = _strip_comments(SOURCE.read_text(errors="replace"))
    body = _function_body(src, "tick")

    compute_call = re.search(r"\bcompute\s*\(", body)
    assert compute_call, "tick() must still call compute() to produce the value"

    # the first lock acquisition in tick(): explicit .lock(), or an RAII guard
    lock_acq = re.search(
        r"\.lock\s*\(\s*\)"
        r"|(?:std::)?(?:lock_guard|unique_lock|scoped_lock)\s*<",
        body,
    )
    assert lock_acq, "tick() must acquire the mutex for the shared update"

    assert compute_call.start() < lock_acq.start(), (
        "compute() must be called BEFORE the lock is acquired (hoisted out of "
        "the critical section), not while the lock is held"
    )

    # and the shared update must still be inside a locked region: a '+=' after
    # the lock acquisition (explicit unlock or RAII scope both satisfy this).
    after_lock = body[lock_acq.start():]
    assert not re.search(r"\bcompute\s*\(", after_lock), (
        "compute() must not run after the lock is acquired: a dead pre-lock call "
        "plus the real compute() inside the critical section defeats the hoist"
    )
    assert re.search(r"\+=", after_lock), (
        "the shared update (total_ += v) must remain under the lock"
    )
