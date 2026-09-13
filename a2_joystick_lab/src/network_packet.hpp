#pragma once

#include "joystick_protocol.hpp"

#include <array>
#include <cstdint>
#include <optional>

namespace a2lab {

constexpr std::uint16_t kPacketVersion = 1;
constexpr std::uint16_t kCommandPacketType = 1;
constexpr std::uint16_t kAckPacketType = 2;
constexpr std::size_t kCommandPacketSize = 68;
constexpr std::size_t kAckPacketSize = 48;

struct MotionCommand {
  float vx{0.0F};
  float vy{0.0F};
  float yaw_rate{0.0F};
};

enum class A2GaitMode { Walk, Run, Climb };

struct MotionLimits {
  float max_vx;
  float max_vy;
  float max_yaw;
};

MotionLimits NativeMotionLimits(A2GaitMode gait, bool high_speed);

struct AxisCalibration {
  float minimum{-1.0F};
  float center{0.0F};
  float maximum{1.0F};
};

struct RemoteAxisCalibration {
  AxisCalibration lx;
  AxisCalibration ly;
  AxisCalibration rx;
  AxisCalibration ry;
  float deadzone{0.05F};
};

float NormalizeAxis(float value, const AxisCalibration& calibration,
                    float deadzone);
MotionCommand CalibratedAxesToMotion(float lx, float ly, float rx,
                                     const RemoteAxisCalibration& calibration,
                                     const MotionLimits& limits);

struct CommandPacket {
  std::uint64_t seq{0};
  std::uint64_t send_steady_ns{0};
  std::uint64_t lowstate_arrival_steady_ns{0};
  std::uint32_t robot_tick_ms{0};
  std::uint16_t buttons{0};
  std::uint16_t flags{0};
  float lx{0.0F};
  float ly{0.0F};
  float rx{0.0F};
  float ry{0.0F};
  MotionCommand command;
};

// The sender provides raw BLE axes/buttons. Velocity mapping is owned by the
// Unitree receiver so gait/speed state has one authoritative implementation.
constexpr std::uint16_t kCommandFlagRawAxes = 1U << 0U;

struct AckPacket {
  std::uint64_t seq{0};
  std::uint64_t original_send_steady_ns{0};
  std::uint64_t receiver_arrival_steady_ns{0};
  std::uint64_t ack_send_steady_ns{0};
  std::int32_t command_result{0};
  std::uint16_t flags{0};
};

constexpr std::uint16_t kAckFlagRobotCommandSent = 1U << 0U;
constexpr std::uint16_t kAckFlagRobotActionSent = 1U << 1U;
constexpr std::uint16_t kAckFlagSuperseded = 1U << 2U;

MotionCommand RemoteToMotionCommand(const RemoteState& remote);

std::array<std::uint8_t, kCommandPacketSize> SerializeCommand(
    const CommandPacket& packet);
std::optional<CommandPacket> ParseCommand(
    const std::uint8_t* data, std::size_t size);

std::array<std::uint8_t, kAckPacketSize> SerializeAck(const AckPacket& packet);
std::optional<AckPacket> ParseAck(const std::uint8_t* data, std::size_t size);

}  // namespace a2lab
