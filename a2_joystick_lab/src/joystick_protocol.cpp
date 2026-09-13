#include "joystick_protocol.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <limits>
#include <sstream>

namespace a2lab {
namespace {

float ReadLittleEndianFloat(const std::array<std::uint8_t, 40>& raw,
                            std::size_t offset) {
  const std::uint32_t bits = static_cast<std::uint32_t>(raw[offset]) |
                             (static_cast<std::uint32_t>(raw[offset + 1]) << 8U) |
                             (static_cast<std::uint32_t>(raw[offset + 2]) << 16U) |
                             (static_cast<std::uint32_t>(raw[offset + 3]) << 24U);
  float value = 0.0F;
  static_assert(sizeof(value) == sizeof(bits), "32-bit float required");
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

}  // namespace

RemoteState ParseRemote(const std::array<std::uint8_t, 40>& raw) {
  RemoteState state;
  state.header = {raw[0], raw[1]};
  state.buttons = static_cast<std::uint16_t>(raw[2]) |
                  (static_cast<std::uint16_t>(raw[3]) << 8U);
  state.lx = ReadLittleEndianFloat(raw, 4);
  state.rx = ReadLittleEndianFloat(raw, 8);
  state.ry = ReadLittleEndianFloat(raw, 12);
  state.trigger_placeholder = ReadLittleEndianFloat(raw, 16);
  state.ly = ReadLittleEndianFloat(raw, 20);
  state.axes_finite = std::isfinite(state.lx) && std::isfinite(state.rx) &&
                      std::isfinite(state.ry) && std::isfinite(state.ly);
  state.all_zero = std::all_of(raw.begin(), raw.end(),
                               [](std::uint8_t byte) { return byte == 0; });
  return state;
}

std::vector<std::string> PressedButtons(std::uint16_t buttons) {
  std::vector<std::string> result;
  for (std::size_t bit = 0; bit < kButtonNames.size(); ++bit) {
    if ((buttons & (static_cast<std::uint16_t>(1U) << bit)) != 0U) {
      result.emplace_back(kButtonNames[bit]);
    }
  }
  return result;
}

std::string Join(const std::vector<std::string>& values,
                 const std::string& separator) {
  std::ostringstream output;
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0) {
      output << separator;
    }
    output << values[i];
  }
  return output.str();
}

std::string RawHex(const std::array<std::uint8_t, 40>& raw) {
  std::ostringstream output;
  output << std::hex << std::setfill('0');
  for (const auto byte : raw) {
    output << std::setw(2) << static_cast<unsigned int>(byte);
  }
  return output.str();
}

TickObservation TickLatencyEstimator::Observe(std::uint32_t raw_tick,
                                              double host_steady_ms) {
  TickObservation result;
  if (!initialized_) {
    initialized_ = true;
    previous_raw_ = raw_tick;
    unwrapped_ = raw_tick;
    best_offset_ms_ = host_steady_ms - static_cast<double>(unwrapped_);
    result.unwrapped_tick_ms = unwrapped_;
    return result;
  }

  const std::uint32_t unsigned_delta = raw_tick - previous_raw_;
  if (unsigned_delta < 0x80000000U) {
    unwrapped_ += unsigned_delta;
    result.tick_delta_ms = static_cast<double>(unsigned_delta);
  } else {
    // A large backwards jump means Basic Service restarted rather than a
    // normal uint32 wrap (normal wrap produces a small unsigned delta).
    unwrapped_ = raw_tick;
    result.reset = true;
    best_offset_ms_ = host_steady_ms - static_cast<double>(unwrapped_);
  }
  previous_raw_ = raw_tick;

  const double offset = host_steady_ms - static_cast<double>(unwrapped_);
  best_offset_ms_ = std::min(best_offset_ms_, offset);
  result.unwrapped_tick_ms = unwrapped_;
  result.excess_delay_ms = std::max(0.0, offset - best_offset_ms_);
  return result;
}

}  // namespace a2lab

