# Intel perf branch mispredict

You are given `/app/branch_mispredict_bad.cpp`, a benchmark that computes a
conditional sum over a large array of bytes: for each element it adds the value
only when `data[i] >= threshold`. Because the data is uniformly random, that
per-element branch is taken roughly half the time in an unpredictable pattern,
so the CPU branch predictor mispredicts constantly and the pipeline stalls.

The included `/app/perf_stat.txt` shows a ~25% `branch-misses` rate and a low
instructions-per-cycle figure — the classic branch-misprediction signature.

Create a fixed implementation that:

1. Preserves the same CLI: `<n> <repeats>`.
2. Preserves the exact same final total (same data, same threshold, same
   arithmetic — only the control flow changes).
3. Removes the hard-to-predict per-element branch from the hot loop by making
   the summation branchless (e.g. a predicated/data-driven expression such as
   `total += (data[i] >= threshold) * data[i];`, a mask, or `std::max`-style
   arithmetic) so the result no longer depends on a mispredicted jump.
4. Writes source at `/app/branch_mispredict_fixed.cpp`.
5. Writes an executable binary at `/app/branch_mispredict_fixed`.
6. Prints a line containing `VALID total=<value>`.

A typical compile command is:

```bash
g++ -O3 -std=c++17 /app/branch_mispredict_fixed.cpp -o /app/branch_mispredict_fixed
```
