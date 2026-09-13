#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace a2lab {

inline constexpr std::array<const char*, 16> kButtonNames = {
    "R1", "L1", "Start", "Select", "R2", "L2", "F1", "F2",
    "A", "B", "X", "Y", "Up", "Right", "Down", "Left"};

struct RemoteState {
  std::array<std::uint8_t, 2> header{};
  std::uint16_t buttons{0};
  float lx{0.0F};
  float rx{0.0F};
  float ry{0.0F};
  float trigger_placeholder{0.0F};
  float ly{0.0F};
  bool axes_finite{true};
  bool all_zero{true};
};

RemoteState ParseRemote(const std::array<std::uint8_t, 40>& raw);
std::vector<std::string> PressedButtons(std::uint16_t buttons);
std::string Join(const std::vector<std::string>& values, const std::string& separator);
std::string RawHex(const std::array<std::uint8_t, 40>& raw);

struct TickObservation {
  std::uint64_t unwrapped_tick_ms{0};
  double tick_delta_ms{0.0};
  double excess_delay_ms{0.0};
  bool reset{false};
};

// LowState.tick is a robot-side 1 ms monotonic counter, not a synchronized
// timestamp. This estimator subtracts the best observed host-minus-robot
// offset, so excess_delay_ms is relative delay above the best sample only.
class TickLatencyEstimator {
 public:
  TickObservation Observe(std::uint32_t raw_tick, double host_steady_ms);

 private:
  bool initialized_{false};
  std::uint32_t previous_raw_{0};
  std::uint64_t unwrapped_{0};
  double best_offset_ms_{0.0};
};

}  // namespace a2lab

