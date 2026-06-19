#!/usr/bin/env bash
set -euo pipefail

cat > /app/branch_mispredict_fixed.cpp <<'CPP'
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <vector>

// Branchless conditional sum: the per-element control-flow branch is replaced
// by a data-driven mask, so there is no hard-to-predict conditional jump in the
// hot loop and the pipeline no longer flushes on random data. The result is
// identical to the baseline (same data, same threshold, same arithmetic).
static long long conditional_sum(const std::vector<int>& data, int threshold) {
    long long total = 0;
    for (std::size_t i = 0; i < data.size(); ++i) {
        const int v = data[i];
        // (v >= threshold) is 0 or 1; multiply instead of branch.
        total += static_cast<long long>(v >= threshold) * v;
    }
    return total;
}

int main(int argc, char** argv) {
    const std::size_t n = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 20000000ULL;
    const long long repeats = argc > 2 ? std::atoll(argv[2]) : 10LL;
    if (n < 1 || repeats < 1) return 2;

    std::vector<int> data(n);
    std::mt19937 rng(0xC0FFEEu);
    std::uniform_int_distribution<int> dist(0, 255);
    for (std::size_t i = 0; i < n; ++i) data[i] = dist(rng);

    const int threshold = 128;
    long long total = 0;
    for (long long r = 0; r < repeats; ++r) {
        total += conditional_sum(data, threshold);
    }

    std::cout << "VALID total=" << total << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 /app/branch_mispredict_fixed.cpp -o /app/branch_mispredict_fixed
