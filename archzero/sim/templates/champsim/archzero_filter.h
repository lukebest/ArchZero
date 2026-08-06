// ArchZero ChampSim prefetcher scaffold (not compiled into stock binary).
// Copy into ChampSim prefetcher/ and wire via champsim_config.json L2C.prefetcher.
#pragma once
#include <cstdint>

struct archzero_filter_state {
  std::uint32_t entries = 256;
  std::uint32_t degree = 2;
  double filter_accuracy = 0.85;
};

void archzero_filter_prefetcher_initialize();
void archzero_filter_prefetcher_cache_operate(std::uint64_t addr, std::uint64_t ip,
                                               std::uint8_t cache_hit, bool useful_prefetch,
                                               std::uint8_t type, std::uint32_t metadata_in);
void archzero_filter_prefetcher_cycle_operate();
void archzero_filter_prefetcher_final_stats();
