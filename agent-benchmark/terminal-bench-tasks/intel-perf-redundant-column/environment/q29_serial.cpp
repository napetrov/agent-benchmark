#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

// Mimics ClickBench Q29:
//   SELECT SUM(c), SUM(c+1), SUM(c+2), ..., SUM(c+89) FROM hits;
//
// The baseline computes each SUM(c+k) by MATERIALIZING a full N-element
// intermediate column `c + k` in memory, then summing it. That is 90 separate
// N-sized buffers built and scanned -- the query becomes memory-bound: it
// touches ~90x the data it needs to. (TMA on the real case showed >90% memory
// bound.) The result we report is a checksum: the sum of all 90 column sums.
//
// This is the SLOW reference. The optimized version must produce the identical
// checksum far faster by avoiding the per-literal materialization.

static const int kColumns = 90;

static std::uint64_t run(const std::vector<std::uint32_t>& c) {
    const std::uint64_t n = c.size();
    std::uint64_t checksum = 0;
    std::vector<std::uint64_t> tmp(n);  // reused intermediate column buffer
    for (int k = 0; k < kColumns; ++k) {
        // materialize the intermediate column (c + k)
        for (std::uint64_t i = 0; i < n; ++i) {
            tmp[i] = static_cast<std::uint64_t>(c[i]) + static_cast<std::uint64_t>(k);
        }
        // sum the materialized column
        std::uint64_t s = 0;
        for (std::uint64_t i = 0; i < n; ++i) s += tmp[i];
        checksum += s;
    }
    return checksum;
}

int main(int argc, char** argv) {
    const int passes = argc > 1 ? std::atoi(argv[1]) : 6;
    if (passes <= 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    // deterministic synthetic column
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
