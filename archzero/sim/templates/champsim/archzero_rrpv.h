// ArchZero ChampSim replacement scaffold (RRPV-style placeholder).
#pragma once
#include <cstdint>

void archzero_rrpv_initialize();
void archzero_rrpv_update(std::uint32_t set, std::uint32_t way, std::uint8_t hit);
std::uint32_t archzero_rrpv_victim(std::uint32_t set);
void archzero_rrpv_final_stats();
