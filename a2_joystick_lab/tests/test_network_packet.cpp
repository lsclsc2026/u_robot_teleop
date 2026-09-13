#include "network_packet.hpp"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>

namespace {

bool Near(float a, float b, float tolerance = 1e-6F) {
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
  a2lab::RemoteState remote;
  remote.lx = -0.5F;
  remote.ly = 0.8F;
  remote.rx = 0.25F;
  remote.ry = -0.1F;
  const auto command = a2lab::RemoteToMotionCommand(remote);
  CHECK(Near(command.vx, 0.4F));
  CHECK(Near(command.vy, 0.15F));
  CHECK(Near(command.yaw_rate, -0.2F));

  const auto walk_low =
      a2lab::NativeMotionLimits(a2lab::A2GaitMode::Walk, false);
  const auto walk_high =
      a2lab::NativeMotionLimits(a2lab::A2GaitMode::Walk, true);
  const auto run_low =
      a2lab::NativeMotionLimits(a2lab::A2GaitMode::Run, false);
  const auto run_high =
      a2lab::NativeMotionLimits(a2lab::A2GaitMode::Run, true);
  const auto climb =
      a2lab::NativeMotionLimits(a2lab::A2GaitMode::Climb, true);
  CHECK(Near(walk_low.max_vx, 0.8F) && Near(walk_low.max_vy, 0.5F) &&
        Near(walk_low.max_yaw, 2.0F));
  CHECK(Near(walk_high.max_vx, 1.5F) && Near(walk_high.max_vy, 0.5F) &&
        Near(walk_high.max_yaw, 2.5F));
  CHECK(Near(run_low.max_vx, 2.5F) && Near(run_low.max_vy, 0.3F) &&
        Near(run_low.max_yaw, 1.5F));
  CHECK(Near(run_high.max_vx, 4.0F) && Near(run_high.max_vy, 0.3F) &&
        Near(run_high.max_yaw, 1.0F));
  CHECK(Near(climb.max_vx, 0.6F) && Near(climb.max_vy, 0.3F) &&
        Near(climb.max_yaw, 1.0F));

  a2lab::RemoteAxisCalibration calibration;
  calibration.lx = {-1.0F, 0.0F, 0.941F};
  calibration.ly = {-0.797F, 0.0F, 0.870F};
  calibration.rx = {-0.823F, 0.0F, 0.953F};
  calibration.deadzone = 0.05F;
  CHECK(Near(a2lab::NormalizeAxis(0.870F, calibration.ly, 0.05F), 1.0F));
  CHECK(Near(a2lab::NormalizeAxis(-0.797F, calibration.ly, 0.05F), -1.0F));
  CHECK(Near(a2lab::NormalizeAxis(0.02F, calibration.ly, 0.05F), 0.0F));
  const auto calibrated = a2lab::CalibratedAxesToMotion(
      0.941F, 0.870F, -0.823F, calibration, walk_low);
  CHECK(Near(calibrated.vx, 0.8F));
  CHECK(Near(calibrated.vy, -0.5F));
  CHECK(Near(calibrated.yaw_rate, 2.0F));

  a2lab::CommandPacket packet;
  packet.seq = 42;
  packet.send_steady_ns = 1000;
  packet.lowstate_arrival_steady_ns = 900;
  packet.robot_tick_ms = 123456;
  packet.buttons = 0x0100;
  packet.flags = a2lab::kCommandFlagRawAxes;
  packet.lx = remote.lx;
  packet.ly = remote.ly;
  packet.rx = remote.rx;
  packet.ry = remote.ry;
  packet.command = command;

  const auto bytes = a2lab::SerializeCommand(packet);
  const auto parsed = a2lab::ParseCommand(bytes.data(), bytes.size());
  CHECK(parsed.has_value());
  CHECK(parsed->seq == packet.seq);
  CHECK(parsed->send_steady_ns == packet.send_steady_ns);
  CHECK(parsed->lowstate_arrival_steady_ns == packet.lowstate_arrival_steady_ns);
  CHECK(parsed->robot_tick_ms == packet.robot_tick_ms);
  CHECK(parsed->buttons == packet.buttons);
  CHECK(parsed->flags == packet.flags);
  CHECK(Near(parsed->lx, packet.lx));
  CHECK(Near(parsed->ly, packet.ly));
  CHECK(Near(parsed->rx, packet.rx));
  CHECK(Near(parsed->ry, packet.ry));
  CHECK(Near(parsed->command.vx, packet.command.vx));
  CHECK(Near(parsed->command.vy, packet.command.vy));
  CHECK(Near(parsed->command.yaw_rate, packet.command.yaw_rate));

  auto invalid_bytes = bytes;
  const float nan = std::numeric_limits<float>::quiet_NaN();
  // vx begins at byte 56 in the fixed 68-byte command packet.
  std::memcpy(invalid_bytes.data() + 56, &nan, sizeof(nan));
  CHECK(!a2lab::ParseCommand(invalid_bytes.data(), invalid_bytes.size()));

  a2lab::AckPacket ack;
  ack.seq = packet.seq;
  ack.original_send_steady_ns = packet.send_steady_ns;
  ack.receiver_arrival_steady_ns = 1100;
  ack.ack_send_steady_ns = 1110;
  ack.command_result = -3;
  ack.flags = a2lab::kAckFlagRobotCommandSent;
  const auto ack_bytes = a2lab::SerializeAck(ack);
  const auto parsed_ack = a2lab::ParseAck(ack_bytes.data(), ack_bytes.size());
  CHECK(parsed_ack.has_value());
  CHECK(parsed_ack->seq == ack.seq);
  CHECK(parsed_ack->original_send_steady_ns == ack.original_send_steady_ns);
  CHECK(parsed_ack->receiver_arrival_steady_ns == ack.receiver_arrival_steady_ns);
  CHECK(parsed_ack->ack_send_steady_ns == ack.ack_send_steady_ns);
  CHECK(parsed_ack->command_result == ack.command_result);
  CHECK(parsed_ack->flags == ack.flags);

  std::cout << "network packet tests passed\n";
  return 0;
}
