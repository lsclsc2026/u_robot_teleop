#include "network_packet.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace a2lab {
namespace {

constexpr std::uint32_t kMagic = 0x504a3241U;  // "A2JP" in little-endian bytes.

float ApplyDeadzone(float value, float deadzone = 0.05F) {
  return (value > -deadzone && value < deadzone) ? 0.0F : value;
}

void PutU16(std::uint8_t*& out, std::uint16_t value) {
  *out++ = static_cast<std::uint8_t>(value & 0xffU);
  *out++ = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
}

void PutU32(std::uint8_t*& out, std::uint32_t value) {
  for (int i = 0; i < 4; ++i) {
    *out++ = static_cast<std::uint8_t>((value >> (i * 8)) & 0xffU);
  }
}

void PutU64(std::uint8_t*& out, std::uint64_t value) {
  for (int i = 0; i < 8; ++i) {
    *out++ = static_cast<std::uint8_t>((value >> (i * 8)) & 0xffU);
  }
}

void PutFloat(std::uint8_t*& out, float value) {
  std::uint32_t bits = 0;
  static_assert(sizeof(bits) == sizeof(value), "32-bit float required");
  std::memcpy(&bits, &value, sizeof(bits));
  PutU32(out, bits);
}

bool GetU16(const std::uint8_t*& in, const std::uint8_t* end,
            std::uint16_t& value) {
  if (end - in < 2) return false;
  value = static_cast<std::uint16_t>(in[0]) |
          (static_cast<std::uint16_t>(in[1]) << 8U);
  in += 2;
  return true;
}

bool GetU32(const std::uint8_t*& in, const std::uint8_t* end,
            std::uint32_t& value) {
  if (end - in < 4) return false;
  value = static_cast<std::uint32_t>(in[0]) |
          (static_cast<std::uint32_t>(in[1]) << 8U) |
          (static_cast<std::uint32_t>(in[2]) << 16U) |
          (static_cast<std::uint32_t>(in[3]) << 24U);
  in += 4;
  return true;
}

bool GetU64(const std::uint8_t*& in, const std::uint8_t* end,
            std::uint64_t& value) {
  if (end - in < 8) return false;
  value = 0;
  for (int i = 0; i < 8; ++i) {
    value |= static_cast<std::uint64_t>(in[i]) << (i * 8);
  }
  in += 8;
  return true;
}

bool GetFloat(const std::uint8_t*& in, const std::uint8_t* end, float& value) {
  std::uint32_t bits = 0;
  if (!GetU32(in, end, bits)) return false;
  std::memcpy(&value, &bits, sizeof(value));
  return true;
}

bool ReadHeader(const std::uint8_t*& in, const std::uint8_t* end,
                std::uint16_t expected_type) {
  std::uint32_t magic = 0;
  std::uint16_t version = 0;
  std::uint16_t type = 0;
  return GetU32(in, end, magic) && magic == kMagic &&
         GetU16(in, end, version) && version == kPacketVersion &&
         GetU16(in, end, type) && type == expected_type;
}

}  // namespace

MotionCommand RemoteToMotionCommand(const RemoteState& remote) {
  MotionCommand command;
  constexpr float kMaxForwardMps = 0.5F;
  constexpr float kMaxLateralMps = 0.3F;
  constexpr float kMaxYawRadps = 0.8F;
  command.vx = ApplyDeadzone(remote.ly) * kMaxForwardMps;
  command.vy = -ApplyDeadzone(remote.lx) * kMaxLateralMps;
  command.yaw_rate = -ApplyDeadzone(remote.rx) * kMaxYawRadps;
  return command;
}

MotionLimits NativeMotionLimits(A2GaitMode gait, bool high_speed) {
  if (gait == A2GaitMode::Climb) return {0.6F, 0.3F, 1.0F};
  if (gait == A2GaitMode::Run && high_speed) return {4.0F, 0.3F, 1.0F};
  if (gait == A2GaitMode::Run) return {2.5F, 0.3F, 1.5F};
  if (high_speed) return {1.5F, 0.5F, 2.5F};
  return {0.8F, 0.5F, 2.0F};
}

float NormalizeAxis(float value, const AxisCalibration& calibration,
                    float deadzone) {
  if (!std::isfinite(value) ||
      !(calibration.minimum < calibration.center) ||
      !(calibration.center < calibration.maximum)) {
    return 0.0F;
  }
  const float normalized = value >= calibration.center
      ? (value - calibration.center) /
            (calibration.maximum - calibration.center)
      : (value - calibration.center) /
            (calibration.center - calibration.minimum);
  const float clamped = std::clamp(normalized, -1.0F, 1.0F);
  const float dz = std::clamp(deadzone, 0.0F, 0.95F);
  const float magnitude = std::fabs(clamped);
  if (magnitude <= dz) return 0.0F;
  return std::copysign((magnitude - dz) / (1.0F - dz), clamped);
}

MotionCommand CalibratedAxesToMotion(
    float lx, float ly, float rx,
    const RemoteAxisCalibration& calibration,
    const MotionLimits& limits) {
  MotionCommand command;
  command.vx = NormalizeAxis(ly, calibration.ly, calibration.deadzone) *
               limits.max_vx;
  command.vy = -NormalizeAxis(lx, calibration.lx, calibration.deadzone) *
               limits.max_vy;
  command.yaw_rate = -NormalizeAxis(rx, calibration.rx, calibration.deadzone) *
                     limits.max_yaw;
  return command;
}

std::array<std::uint8_t, kCommandPacketSize> SerializeCommand(
    const CommandPacket& packet) {
  std::array<std::uint8_t, kCommandPacketSize> data{};
  auto* out = data.data();
  PutU32(out, kMagic);
  PutU16(out, kPacketVersion);
  PutU16(out, kCommandPacketType);
  PutU64(out, packet.seq);
  PutU64(out, packet.send_steady_ns);
  PutU64(out, packet.lowstate_arrival_steady_ns);
  PutU32(out, packet.robot_tick_ms);
  PutU16(out, packet.buttons);
  PutU16(out, packet.flags);
  PutFloat(out, packet.lx);
  PutFloat(out, packet.ly);
  PutFloat(out, packet.rx);
  PutFloat(out, packet.ry);
  PutFloat(out, packet.command.vx);
  PutFloat(out, packet.command.vy);
  PutFloat(out, packet.command.yaw_rate);
  return data;
}

std::optional<CommandPacket> ParseCommand(const std::uint8_t* data,
                                          std::size_t size) {
  if (size < kCommandPacketSize) return std::nullopt;
  const auto* in = data;
  const auto* end = data + size;
  if (!ReadHeader(in, end, kCommandPacketType)) return std::nullopt;

  CommandPacket packet;
  if (!GetU64(in, end, packet.seq) ||
      !GetU64(in, end, packet.send_steady_ns) ||
      !GetU64(in, end, packet.lowstate_arrival_steady_ns) ||
      !GetU32(in, end, packet.robot_tick_ms) ||
      !GetU16(in, end, packet.buttons) || !GetU16(in, end, packet.flags) ||
      !GetFloat(in, end, packet.lx) || !GetFloat(in, end, packet.ly) ||
      !GetFloat(in, end, packet.rx) || !GetFloat(in, end, packet.ry) ||
      !GetFloat(in, end, packet.command.vx) ||
      !GetFloat(in, end, packet.command.vy) ||
      !GetFloat(in, end, packet.command.yaw_rate)) {
    return std::nullopt;
  }
  const std::array<float, 7> values{
      packet.lx, packet.ly, packet.rx, packet.ry, packet.command.vx,
      packet.command.vy, packet.command.yaw_rate};
  if (!std::all_of(values.begin(), values.end(),
                   [](float value) { return std::isfinite(value); })) {
    return std::nullopt;
  }
  return packet;
}

std::array<std::uint8_t, kAckPacketSize> SerializeAck(const AckPacket& packet) {
  std::array<std::uint8_t, kAckPacketSize> data{};
  auto* out = data.data();
  PutU32(out, kMagic);
  PutU16(out, kPacketVersion);
  PutU16(out, kAckPacketType);
  PutU64(out, packet.seq);
  PutU64(out, packet.original_send_steady_ns);
  PutU64(out, packet.receiver_arrival_steady_ns);
  PutU64(out, packet.ack_send_steady_ns);
  PutU32(out, static_cast<std::uint32_t>(packet.command_result));
  PutU16(out, packet.flags);
  PutU16(out, 0);
  return data;
}

std::optional<AckPacket> ParseAck(const std::uint8_t* data, std::size_t size) {
  if (size < kAckPacketSize) return std::nullopt;
  const auto* in = data;
  const auto* end = data + size;
  if (!ReadHeader(in, end, kAckPacketType)) return std::nullopt;

  AckPacket packet;
  if (!GetU64(in, end, packet.seq) ||
      !GetU64(in, end, packet.original_send_steady_ns) ||
      !GetU64(in, end, packet.receiver_arrival_steady_ns) ||
      !GetU64(in, end, packet.ack_send_steady_ns)) {
    return std::nullopt;
  }
  std::uint32_t result = 0;
  std::uint16_t reserved = 0;
  if (!GetU32(in, end, result) || !GetU16(in, end, packet.flags) ||
      !GetU16(in, end, reserved)) {
    return std::nullopt;
  }
  packet.command_result = static_cast<std::int32_t>(result);
  return packet;
}

}  // namespace a2lab
