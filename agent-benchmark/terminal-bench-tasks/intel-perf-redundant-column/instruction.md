# Intel perf redundant column materialization

You are given `/app/q29_serial.cpp`, a slow reference that mimics ClickBench
Q29:

```sql
SELECT SUM(c), SUM(c+1), SUM(c+2), ..., SUM(c+89) FROM hits;
```

For each of the 90 literals it **materializes** a full N-element intermediate
column `c + k` in memory and then sums it — 90 separate N-sized buffers built
and scanned. The included `/app/perf_tma.txt` shows the workload is ~78% memory
bound: the arithmetic is trivial, but it moves ~90× the data it needs to. The
program reports a checksum (the sum of all 90 column sums) as `q29=<value>`.

The key observation is algebraic:

```text
SUM(c + k) == SUM(c) + k * COUNT(c)
```

So every one of the 90 results can be derived from a **single** pass over `c`
(computing `SUM(c)` and `N = COUNT(c)`) plus 90 cheap scalar corrections — no
intermediate columns at all.

Create a fixed implementation that:

1. Preserves the CLI: `<passes>` (same meaning as the baseline).
2. Produces the **identical** checksum as `/app/q29_serial` for the same input.
3. Eliminates the per-literal column materialization: make one pass over `c`
   and derive the 90 sums with `SUM(c) + k * N`.
4. Writes source at `/app/q29_fast.cpp`.
5. Writes an executable binary at `/app/q29_fast`.
6. Prints a line containing `VALID q29=<value>`.

A typical compile command is:

```bash
g++ -O3 -std=c++17 /app/q29_fast.cpp -o /app/q29_fast
```

The verifier checks that the checksum exactly matches the serial baseline and
that the optimized binary is at least 1.8× faster (the rewrite removes ~89 of
the 90 passes over memory, so the real margin is far larger; the floor is set
low to stay robust on slower CI hosts).
