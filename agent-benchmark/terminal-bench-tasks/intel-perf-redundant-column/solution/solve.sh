#!/usr/bin/env bash
set -euo pipefail

cat > /app/q29_fast.cpp <<'CPP'
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

// Optimized ClickBench Q29: instead of materializing 90 intermediate columns,
// use SUM(c + k) == SUM(c) + k * COUNT(c). One pass over `c` gives SUM(c) and
// N = COUNT(c); the 90 column sums are then scalar corrections. Memory traffic
// drops from ~90 passes to 1. The reported checksum (sum of the 90 column sums)
// is bit-identical to the serial baseline.
static const int kColumns = 90;

static std::uint64_t run(const std::vector<std::uint32_t>& c) {
    const std::uint64_t n = c.size();
    std::uint64_t sum_c = 0;            // single pass over the column
    for (std::uint64_t i = 0; i < n; ++i) sum_c += c[i];

    std::uint64_t checksum = 0;
    for (std::uint64_t k = 0; k < static_cast<std::uint64_t>(kColumns); ++k) {
        // SUM(c + k) = SUM(c) + k * N   (N = COUNT(c))
        checksum += sum_c + k * n;
    }
    return checksum;
}

int main(int argc, char** argv) {
    const int passes = argc > 1 ? std::atoi(argv[1]) : 6;
    if (passes <= 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    const std::uint64_t n = 2'000'000ULL;
    std::vector<std::uint32_t> c(n);
    std::uint64_t x = 88172645463325252ULL;
    for (std::uint64_t i = 0; i < n; ++i) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        c[i] = static_cast<std::uint32_t>(x & 0xFFFF);
    }

    std::uint64_t checksum = 0;
    for (int p = 0; p < passes; ++p) checksum += run(c);

    std::cout << "VALID q29=" << checksum << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 /app/q29_fast.cpp -o /app/q29_fast
