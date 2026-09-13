#include "joystick_protocol.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>

namespace {

void PutFloat(std::array<std::uint8_t, 40>& raw, std::size_t offset, float value) {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  raw[offset] = static_cast<std::uint8_t>(bits & 0xffU);
  raw[offset + 1] = static_cast<std::uint8_t>((bits >> 8U) & 0xffU);
  raw[offset + 2] = static_cast<std::uint8_t>((bits >> 16U) & 0xffU);
  raw[offset + 3] = static_cast<std::uint8_t>((bits >> 24U) & 0xffU);
}

bool Near(double a, double b, double tolerance = 1e-5) {
  return std::fabs(a - b) < tolerance;
}

#define CHECK(condition)                                                        \
  do {                                                                          \
    if (!(condition)) {                                                         \
      std::cerr << "check failed at line " << __LINE__ << ": " #condition       \
                << "\n";                                                       \
      return 1;                                                                 \
    }                                                                           \
  } while (false)

}  // namespace

int main() {
  std::array<std::uint8_t, 40> raw{};
  raw[0] = 0xfe;
  raw[1] = 0xef;
  raw[2] = 0x01;  // R1
  raw[3] = 0x88;  // Y + Left
  PutFloat(raw, 4, 0.25F);
  PutFloat(raw, 8, -0.5F);
  PutFloat(raw, 12, 0.75F);
  PutFloat(raw, 16, 1.0F);
  PutFloat(raw, 20, -1.0F);

  const auto state = a2lab::ParseRemote(raw);
  CHECK(state.header[0] == 0xfe && state.header[1] == 0xef);
  CHECK(state.buttons == 0x8801U);
  CHECK(Near(state.lx, 0.25));
  CHECK(Near(state.rx, -0.5));
  CHECK(Near(state.ry, 0.75));
  CHECK(Near(state.ly, -1.0));
  CHECK(state.axes_finite);
  CHECK(!state.all_zero);

  const auto names = a2lab::PressedButtons(state.buttons);
  CHECK(a2lab::Join(names, "+") == "R1+Y+Left");

  a2lab::TickLatencyEstimator estimator;
  auto observation = estimator.Observe(1000U, 5000.0);
  CHECK(Near(observation.excess_delay_ms, 0.0));
  observation = estimator.Observe(1010U, 5010.0);
  CHECK(Near(observation.tick_delta_ms, 10.0));
  CHECK(Near(observation.excess_delay_ms, 0.0));
  observation = estimator.Observe(1020U, 5025.0);
  CHECK(Near(observation.excess_delay_ms, 5.0));

  a2lab::TickLatencyEstimator wrap_estimator;
  wrap_estimator.Observe(0xfffffff0U, 1000.0);
  observation = wrap_estimator.Observe(0x00000004U, 1020.0);
  CHECK(Near(observation.tick_delta_ms, 20.0));
  CHECK(!observation.reset);

  std::cout << "protocol tests passed\n";
  return 0;
}
