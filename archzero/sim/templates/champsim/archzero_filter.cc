// ArchZero filtered-prefetch scaffold — replace body with real mechanism.
#include "archzero_filter.h"
#include <cstdio>

static archzero_filter_state g_state;

void archzero_filter_prefetcher_initialize() {
  std::fprintf(stderr, "[archzero] filter prefetcher init entries=%u degree=%u\n",
               g_state.entries, g_state.degree);
}

void archzero_filter_prefetcher_cache_operate(std::uint64_t /*addr*/, std::uint64_t /*ip*/,
                                               std::uint8_t /*cache_hit*/, bool /*useful_prefetch*/,
                                               std::uint8_t /*type*/, std::uint32_t /*metadata_in*/) {
  // TODO: dead-block filter + limited-degree prefetch issue.
}

void archzero_filter_prefetcher_cycle_operate() {}
void archzero_filter_prefetcher_final_stats() {
  std::fprintf(stderr, "[archzero] filter prefetcher final_stats\n");
}
