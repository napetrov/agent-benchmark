#!/usr/bin/env bash
set -euo pipefail

cat > /app/solution.py <<'PY'
import dpnp as np
import numpy


def run():
    x = np.arange(1_000_000, dtype=np.float64)
    y = np.sin(x) + np.cos(x)
    mean_val = float(np.mean(y))
    std_val = float(np.std(y))
    try:
        min_val = float(np.min(y))
        max_val = float(np.max(y))
    except NotImplementedError:
        host = np.asnumpy(y)
        min_val = float(numpy.min(host))
        max_val = float(numpy.max(host))
    sig = mean_val + std_val * 1e4 + min_val * 1e8 + max_val * 1e12
    print(f"VALID dpnp sig={sig:.6f}")


if __name__ == "__main__":
    run()
PY

echo "solution written to /app/solution.py"
