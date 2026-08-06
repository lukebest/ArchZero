// ArchZero RRPV replacement scaffold — replace with real history-aware policy.
#include "archzero_rrpv.h"
#include <cstdio>

void archzero_rrpv_initialize() {
  std::fprintf(stderr, "[archzero] rrpv replacement init\n");
}

void archzero_rrpv_update(std::uint32_t /*set*/, std::uint32_t /*way*/, std::uint8_t /*hit*/) {}

std::uint32_t archzero_rrpv_victim(std::uint32_t /*set*/) { return 0; }

void archzero_rrpv_final_stats() {
  std::fprintf(stderr, "[archzero] rrpv replacement final_stats\n");
}
