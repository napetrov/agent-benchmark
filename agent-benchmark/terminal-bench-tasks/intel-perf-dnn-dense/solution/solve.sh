#!/usr/bin/env bash
set -euo pipefail

cat > /app/dense_fast.cpp <<'CPP'
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <immintrin.h>
#include <iomanip>
#include <iostream>
#include <vector>

static inline float input_value(std::size_t j) {
    return static_cast<float>((j * 13u + 7u) % 256u) * 0.00390625f - 0.5f;
}
static inline float weight_value(std::size_t i, std::size_t j) {
    return static_cast<float>((i * 31u + j * 17u + 5u) % 512u) * 0.001953125f - 0.5f;
}
static inline float bias_value(std::size_t i) {
    return static_cast<float>((i * 7u + 3u) % 128u) * 0.0078125f - 0.5f;
}

// Vector-sequential reduction: four SSE2 accumulators, 16 elements per step,
// to break the loop-carried dependency chain (Optimization 3).
static inline float dense_dot(const float* in, const float* w, std::size_t n, float bias) {
    __m128 acc0 = _mm_setzero_ps(), acc1 = _mm_setzero_ps();
    __m128 acc2 = _mm_setzero_ps(), acc3 = _mm_setzero_ps();
    std::size_t j = 0;
    for (; j + 15 < n; j += 16) {
        acc0 = _mm_add_ps(acc0, _mm_mul_ps(_mm_loadu_ps(in + j +  0), _mm_loadu_ps(w + j +  0)));
        acc1 = _mm_add_ps(acc1, _mm_mul_ps(_mm_loadu_ps(in + j +  4), _mm_loadu_ps(w + j +  4)));
        acc2 = _mm_add_ps(acc2, _mm_mul_ps(_mm_loadu_ps(in + j +  8), _mm_loadu_ps(w + j +  8)));
        acc3 = _mm_add_ps(acc3, _mm_mul_ps(_mm_loadu_ps(in + j + 12), _mm_loadu_ps(w + j + 12)));
    }
    __m128 acc = _mm_add_ps(_mm_add_ps(acc0, acc1), _mm_add_ps(acc2, acc3));
    __m128 shuf = _mm_shuffle_ps(acc, acc, _MM_SHUFFLE(2, 3, 0, 1));
    __m128 sums = _mm_add_ps(acc, shuf);
    shuf = _mm_shuffle_ps(sums, sums, _MM_SHUFFLE(1, 0, 3, 2));
    sums = _mm_add_ps(sums, shuf);
    float sum = _mm_cvtss_f32(sums) + bias;
    for (; j < n; ++j) sum += in[j] * w[j];  // scalar tail
    return sum;
}

int main(int argc, char** argv) {
    const std::size_t passes  = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 240ULL;
    const std::size_t neurons = 4096;
    const std::size_t inputs  = 2048;

    std::vector<float> input(inputs);
    for (std::size_t j = 0; j < inputs; ++j) input[j] = input_value(j);

    std::vector<float> weights(neurons * inputs);
    std::vector<float> biases(neurons);
    for (std::size_t i = 0; i < neurons; ++i) {
        biases[i] = bias_value(i);
        for (std::size_t j = 0; j < inputs; ++j) {
            weights[i * inputs + j] = weight_value(i, j);
        }
    }

    double checksum = 0.0;
    for (std::size_t p = 0; p < passes; ++p) {
        double pass_sum = 0.0;
        for (std::size_t i = 0; i < neurons; ++i) {
            float sum = dense_dot(input.data(), &weights[i * inputs], inputs, biases[i]);
            float out = sum > 0.0f ? sum : 0.01f * sum;  // leaky ReLU
            pass_sum += out;
        }
        checksum += pass_sum / static_cast<double>(neurons);
    }

    if (!std::isfinite(checksum)) {
        std::cerr << "INVALID_RESULT\n";
        return 1;
    }
    std::cout << std::setprecision(17) << "VALID dnn=" << checksum << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 -msse2 /app/dense_fast.cpp -o /app/dense_fast
