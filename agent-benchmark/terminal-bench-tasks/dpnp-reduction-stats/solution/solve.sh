#!/usr/bin/env bash
set -euo pipefail

cat > /app/solution.py <<'PY'
import dpnp

ROWS = 10_000
COLS = 256


def run():
    i = dpnp.arange(ROWS, dtype=dpnp.float64).reshape(ROWS, 1)
    j = dpnp.arange(COLS, dtype=dpnp.float64).reshape(1, COLS)
    M = ((i * 31 + j * 17) % 997) - 498

    col_sum = dpnp.sum(M, axis=0)
    col_mean = dpnp.mean(M, axis=0)
    col_std = dpnp.std(M, axis=0)

    sig = (
        float(dpnp.sum(col_sum))
        + float(dpnp.sum(col_mean)) * 1e4
        + float(dpnp.sum(col_std)) * 1e8
    )
    print(f"VALID dpnp sig={sig:.6f}")


if __name__ == "__main__":
    run()
PY

echo "solution written to /app/solution.py"
