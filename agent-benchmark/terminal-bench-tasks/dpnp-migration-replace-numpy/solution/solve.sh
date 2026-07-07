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
    # Print each metric independently for verification
    print(f"VALID mean={mean_val:.9e} std={std_val:.9e} min={min_val:.9e} max={max_val:.9e}")


if __name__ == "__main__":
    run()
PY

echo "solution written to /app/solution.py"
