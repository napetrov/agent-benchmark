#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path

BINARY = Path("/app/sp_fixed")
SOURCE = Path("/app/sp_fixed.cpp")
TIMEOUT = 60.0


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


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
    assert SOURCE.exists(), "write /app/sp_fixed.cpp"
    assert BINARY.exists(), "compile /app/sp_fixed"
    assert os.access(BINARY, os.X_OK), "/app/sp_fixed is not executable"


def test_total_unchanged_at_several_thread_counts():
    for threads, iters in [(2, 2000000), (4, 2000000), (8, 1000000)]:
        total, _ = _run(threads, iters)
        assert total == threads * iters * 7, (
            f"wrong total at threads={threads} iters={iters}: got {total}"
        )


def test_terminates_within_time_limit():
    # the layout fix yields only a modest gain (the refcount stays truly shared),
    # too small to gate on reliably on a CPU-pinned CI host. We assert progress
    # and termination rather than a flaky speedup margin (see difficulty-rubric).
    total, elapsed = _run(8, 1000000)
    assert total == 8 * 1000000 * 7
    assert elapsed < 30.0, f"run took {elapsed:.1f}s"


def test_source_does_not_make_shared_the_contended_object():
    src = _strip_comments(SOURCE.read_text(errors="replace"))

    # cache-line alignment/padding evidence: explicit alignas/aligned with any
    # argument (incl. a named constant like CACHELINE), or the standard hint.
    aligned = re.search(r"\balignas\s*\(", src) \
        or re.search(r"\baligned\s*\(", src) \
        or "hardware_destructive_interference_size" in src

    # co-locating allocators (make_shared/allocate_shared) put the control block
    # in the same heap block as the payload. instruction.md allows them ONLY if
    # the payload is also cache-line-aligned/padded so the refcount and the hot
    # read-only field still land on different lines; reject them otherwise.
    co_located = re.search(r"(?:make_shared|allocate_shared)\s*<\s*Payload\b", src)
    assert not (co_located and not aligned), (
        "make_shared/allocate_shared<Payload> co-locates the control block with "
        "the payload; allocate the object separately (shared_ptr<Payload>(new "
        "Payload(...))) or cache-line-align/pad the payload"
    )

    # positive evidence of a fix: either a separate allocation (shared_ptr from
    # new Payload, helper factory, allocator) or explicit cache-line alignment.
    separate_alloc = re.search(r"new\s+Payload\b", src)
    assert separate_alloc or aligned, (
        "separate the control block from the payload (shared_ptr<Payload>(new "
        "Payload(...))) and/or cache-line-align the payload"
    )
