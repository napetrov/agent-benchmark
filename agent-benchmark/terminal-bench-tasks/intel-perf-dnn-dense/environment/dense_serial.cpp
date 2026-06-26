#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <vector>

// Deterministic, formula-driven inputs (no RNG): the result is reproducible
// across builds, so an optimized variant can be compared bit-for-bit.
static inline float input_value(std::size_t j) {
    return static_cast<float>((j * 13u + 7u) % 256u) * 0.00390625f - 0.5f;
}
static inline float weight_value(std::size_t i, std::size_t j) {
    return static_cast<float>((i * 31u + j * 17u + 5u) % 512u) * 0.001953125f - 0.5f;
}
static inline float bias_value(std::size_t i) {
    return static_cast<float>((i * 7u + 3u) % 128u) * 0.0078125f - 0.5f;
}

// Single-accumulator dense-layer forward pass with a leaky-ReLU activation.
// The inner loop is a vector-sequential reduction with a loop-carried
// dependency on `sum`, which serializes the floating-point adds.
int main(int argc, char** argv) {
    const std::size_t passes  = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 240ULL;
    const std::size_t neurons = 4096;
    const std::size_t inputs  = 2048;  // multiple of 16

    std::vector<float> input(inputs);
    for (std::size_t j = 0; j < inputs; ++j) input[j] = input_value(j);

    // Precompute the weight matrix and biases once so the timed inner loop is a
    // pure reduction (the pattern under optimization), not index arithmetic.
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
            const float* w_row = &weights[i * inputs];
            float sum = biases[i];
            for (std::size_t j = 0; j < inputs; ++j) {
                sum += input[j] * w_row[j];
            }
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
