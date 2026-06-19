#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <vector>

// Conditional sum over a large array of bytes: for each element the value is
// added only when `data[i] >= threshold`. Because the data is uniformly random,
// that per-element branch is taken in an unpredictable ~50/50 pattern, so the
// CPU branch predictor mispredicts on roughly every other element and the
// pipeline flushes -- a textbook branch-misprediction stall in the hot loop.
//
// The `asm volatile` barrier in the taken path keeps this a *real* conditional
// branch: without it, the optimizer would fold the whole thing into a branchless
// conditional-move and there would be nothing to mispredict.
static long long conditional_sum(const std::vector<int>& data, int threshold) {
    long long total = 0;
    for (std::size_t i = 0; i < data.size(); ++i) {
        if (data[i] >= threshold) {           // hard-to-predict data-dependent branch
            total += data[i];
            asm volatile("" : "+r"(total));   // keep a real conditional jump here
        }
    }
    return total;
}

int main(int argc, char** argv) {
    const std::size_t n = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 20000000ULL;
    const long long repeats = argc > 2 ? std::atoll(argv[2]) : 10LL;
    if (n < 1 || repeats < 1) return 2;

    // Deterministic data so the baseline and any fix sum to the same value.
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
