# Intel perf spinlock backoff

You are given `/app/spin_bad.cpp`, a contended-counter benchmark guarded by a
**test-and-test-and-set (TTAS) spinlock**. The lock already spins on an ordinary
read of the flag and only attempts the atomic `exchange` once the flag looks
free, so the classic "write on every spin" storm is already gone.

A problem remains. The included `/app/perf_annotate.txt` shows the cost
concentrated on the `lock xchg` exchange instruction, spiking right after each
`unlock()`: when the flag is cleared, **every** waiting core sees the free flag
in the same window and fires the atomic exchange simultaneously. Only one wins;
the others re-read and collide again on the next release. This release-time
**CAS storm** (thundering herd) does not scale with core count.

Create a fixed implementation that:

1. Preserves the CLI: `<threads> <iterations>`.
2. Preserves the exact final total (`threads * iterations`).
3. Keeps the read-only (TTAS) spin, and adds **bounded exponential backoff** to
   the spin loop so waiters do not all retry the exchange at the same instant:
   - a backoff counter that grows multiplicatively (e.g. doubles) after a failed
     acquire attempt,
   - a cap so the backoff cannot grow without bound,
   - a CPU-relax/pause body for the delay (e.g. `_mm_pause()`,
     `__builtin_ia32_pause()`, inline `pause`, or `std::this_thread::yield()`).
   (This mirrors the backoff added to the glibc nptl spin loop and to oneTBB's
   `spin_mutex`.)
4. Writes source at `/app/spin_fixed.cpp`.
5. Writes an executable binary at `/app/spin_fixed`.
6. Prints a line containing `VALID count=<value>`.

A typical compile command is:

```bash
g++ -O3 -std=c++17 -pthread /app/spin_fixed.cpp -o /app/spin_fixed
```

The verifier checks that mutual exclusion still holds (exact total at several
thread counts), that the lock terminates well within the time limit at high
contention (no livelock or unbounded backoff), and that the source spins on an
ordinary load and applies a capped, multiplicatively-growing backoff with a
relax/pause body before retrying the atomic acquire.
