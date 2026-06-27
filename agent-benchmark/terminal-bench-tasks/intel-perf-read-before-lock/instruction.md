# Intel perf read before lock

You are given `/app/crit_bad.cpp`, a multithreaded benchmark in which workers
fold a per-iteration value into a shared total under a `std::mutex`. The
included `/app/perf_offcpu.txt` shows threads spending ~92% of their time
blocked in `__lll_lock_wait`, while the lock holder spends ~73% of its locked
window inside `compute()`.

`compute()` is a pure function of the loop index: it reads no shared state and
writes no shared state, so it does **not** need the lock. But it runs *while the
lock is held*, so every other worker is blocked for the full duration of that
lock-independent work. The only operation that actually needs protection is the
single `total_ += v`. The critical section is bloated with work that belongs
outside it. (This is the shape of the ClickHouse `ThreadGroupStatus::mutex` fix:
move the heavy/temporary work out of the critical section.)

Create a fixed implementation that:

1. Preserves the CLI: `<threads> <iterations>`.
2. Preserves the exact final total (same reference sum as the baseline).
3. Shrinks the critical section to only the shared update: compute the
   per-iteration value **before** acquiring the lock, and hold the lock only for
   the operation that touches shared state (`total_ += v`).
4. Writes source at `/app/crit_fixed.cpp`.
5. Writes an executable binary at `/app/crit_fixed`.
6. Prints a line containing `VALID total=<value>`.

A typical compile command is:

```bash
g++ -O3 -std=c++17 -pthread /app/crit_fixed.cpp -o /app/crit_fixed
```

The verifier checks that the result is unchanged at several thread counts, that
the program terminates well within the time limit under high contention, and
that the lock-independent `compute()` call no longer happens inside the locked
region.
