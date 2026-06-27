#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

// A single shared object is accessed by many threads. Each thread, in a hot
// loop, copies the shared_ptr (atomically bumps the reference count up, then
// down when the copy dies) and reads a hot, read-only field of the object.
//
// The bug is the allocation strategy. `std::make_shared<Payload>()` places the
// control block (which holds the atomic _M_use_count / _M_weak_count) in the
// SAME heap block as the object, immediately adjacent to its first members. So
// the reference-count word and the read-only `value` field land on the same
// 64-byte cache line. Every refcount inc/dec (a write, from every thread)
// invalidates that line, and every read of `value` then takes a coherence miss
// even though no thread ever writes `value`. That is false sharing between the
// shared_ptr control block and the object payload -- the exact pattern fixed in
// Hologres by not using make_shared (allocating the object separately from its
// control block) or padding between the refcount and the object.
struct Payload {
    std::uint64_t value;   // hot, read-only; shares a line with the refcount under make_shared
    char pad[40];
    explicit Payload(std::uint64_t v) : value(v), pad{} {}
};

int main(int argc, char** argv) {
    const unsigned threads = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 4u;
    const std::uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 4000000ULL;
    if (threads == 0 || iters == 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    // make_shared: control block (refcount) co-located with the object payload
    std::shared_ptr<Payload> obj = std::make_shared<Payload>(7ULL);

    std::vector<std::uint64_t> sums(threads, 0);
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t) {
        pool.emplace_back([&, t] {
            std::uint64_t local = 0;
            for (std::uint64_t i = 0; i < iters; ++i) {
                std::shared_ptr<Payload> copy = obj;  // atomic refcount inc/dec (write)
                local += copy->value;                 // read-only field, false-shared
            }
            sums[t] = local;
        });
    }
    for (auto& th : pool) th.join();

    std::uint64_t total = 0;
    for (auto s : sums) total += s;
    const std::uint64_t expected = static_cast<std::uint64_t>(threads) * iters * 7ULL;
    if (total != expected) { std::cerr << "INVALID_RESULT total=" << total << "\n"; return 1; }
    std::cout << "VALID total=" << total << "\n";
    return 0;
}
