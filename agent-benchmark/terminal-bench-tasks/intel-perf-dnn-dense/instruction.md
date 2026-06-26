# Intel perf DNN dense layer

You are given `/app/dense_serial.cpp`, a deterministic dense-layer (fully
connected) forward-pass benchmark with a leaky-ReLU activation. The included
`/app/perf_stat.txt` shows low IPC with low cache and branch miss rates, which
points at a compute/dependency bottleneck rather than memory or I/O.

The hot inner loop computes one neuron's pre-activation as a reduction:

```cpp
float sum = biases[i];
for (std::size_t j = 0; j < inputs; ++j)
    sum += input[j] * w_row[j];
```

The single `sum` accumulator creates a loop-carried dependency that serializes
the floating-point adds. This is the vector-sequential reduction pattern.

Create an optimized implementation that:

1. Computes the same forward-pass checksum for the same optional CLI argument
   `<passes>` (the layer dimensions are fixed in the program).
2. Breaks the single loop-carried accumulator dependency using independent
   partial accumulators and/or SIMD intrinsics (an unrolled SSE2/AVX2 reduction
   is a good fit; the input size is a multiple of 16). Keep a scalar tail.
3. Preserves the leaky-ReLU activation (`out = sum > 0 ? sum : 0.01f * sum`).
4. Writes source at `/app/dense_fast.cpp`.
5. Writes an executable binary at `/app/dense_fast`.
6. Prints a line containing `VALID dnn=<value>`.

Do not change the mathematical inputs or layer dimensions. The verifier
compares your checksum against the serial reference within a small
floating-point tolerance and checks that your binary runs faster.

A typical compile command is:

```bash
g++ -O3 -std=c++17 -msse2 /app/dense_fast.cpp -o /app/dense_fast
```
