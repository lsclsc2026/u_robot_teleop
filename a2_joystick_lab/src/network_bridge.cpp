#include "network_packet.hpp"
#include "a2_button_mapper.hpp"

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>
#include <unitree/robot/a2/sport/sport_client.hpp>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace {

using LowState = unitree_hg::msg::dds_::LowState_;
using Clock = std::chrono::steady_clock;

std::atomic_bool g_stop{false};

void SignalHandler(int) {
  g_stop.store(true);
}

std::uint64_t SteadyNs() {
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          Clock::now().time_since_epoch())
          .count());
}

std::uint64_t UnixNs() {
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          std::chrono::system_clock::now().time_since_epoch())
          .count());
}

double NsToMs(std::uint64_t ns) {
  return static_cast<double>(ns) / 1'000'000.0;
}

struct Options {
  std::string mode = "loopback";
  std::string interface = "eth1";
  std::string topic = "rt/lowstate";
  std::string target = "127.0.0.1";
  std::string listen = "0.0.0.0";
  std::string ack_target = "127.0.0.1";
  int port = 39001;
  int ack_port = 39002;
  int duration_sec = 20;
  double send_hz = 50.0;
  double command_hz = 20.0;
  int soft_timeout_ms = 150;
  int hard_timeout_ms = 500;
  a2lab::RemoteAxisCalibration axis_calibration{
      {-1.000F, 0.0F, 0.941F},
      {-0.797F, 0.0F, 0.870F},
      {-0.823F, 0.0F, 0.953F},
      {-1.000F, 0.0F, 1.000F},
      0.05F};
  bool enable_robot_command = false;
  bool balance_stand_on_start = false;
  bool native_button_map = false;
  bool enable_special_actions = false;
  std::string allowed_source;
  std::string deadman_button = "F1";
  std::uint16_t deadman_mask = 1U << 6U;  // F1, safer than R1 on A2 remote.
  std::string csv = "logs/network_loopback.csv";
};

std::optional<std::uint16_t> ButtonMaskByName(const std::string& name) {
  for (std::size_t i = 0; i < a2lab::kButtonNames.size(); ++i) {
    if (name == a2lab::kButtonNames[i]) {
      return static_cast<std::uint16_t>(1U << i);
    }
  }
  return std::nullopt;
}

void PrintUsage(const char* argv0) {
  std::cerr
      << "Usage: " << argv0 << " [options]\n"
      << "  --mode loopback|sender|receiver  default loopback\n"
      << "  --interface eth1                 DDS interface for sender/loopback\n"
      << "  --topic rt/lowstate              DDS LowState topic\n"
      << "  --target 127.0.0.1               UDP command target\n"
      << "  --listen 0.0.0.0                 UDP receiver bind address\n"
      << "  --ack-target 127.0.0.1           UDP ACK target\n"
      << "  --port 39001                     command UDP port\n"
      << "  --ack-port 39002                 ACK UDP port\n"
      << "  --duration 20                    seconds, 0 means Ctrl-C\n"
      << "  --send-hz 50                     command packet rate\n"
      << "  --command-hz 20                  max SportClient command rate\n"
      << "  --soft-timeout-ms 150            brief loss sends Move(0,0,0)\n"
      << "  --hard-timeout-ms 500            prolonged loss latches StopMove\n"
      << "  --axis-deadzone 0.05             normalized receiver-side deadzone\n"
      << "  --lx-min/center/max VALUE        per-axis BLE calibration\n"
      << "  --ly-min/center/max VALUE        per-axis BLE calibration\n"
      << "  --rx-min/center/max VALUE        per-axis BLE calibration\n"
      << "  --ry-min/center/max VALUE        per-axis BLE calibration\n"
      << "  --allowed-source 192.168.123.200 only accept commands from this IPv4\n"
      << "  --enable-robot-command           receiver sends A2 Move/StopMove\n"
      << "  --deadman-button F1|none         button gate or neutral-armed direct control\n"
      << "  --balance-stand-on-start         call BalanceStand once at receiver start\n"
      << "  --native-button-map              map documented A2 remote button combinations\n"
      << "  --enable-special-actions         allow flips/handstand/biped actions (dangerous)\n"
      << "  --csv logs/network_loopback.csv  sender latency CSV\n";
}

std::optional<Options> ParseArgs(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&](const char* name) -> std::optional<std::string> {
      if (i + 1 >= argc) {
        std::cerr << "Missing value for " << name << "\n";
        return std::nullopt;
      }
      return std::string(argv[++i]);
    };

    if (arg == "--mode") {
      auto v = value("--mode");
      if (!v) return std::nullopt;
      options.mode = *v;
    } else if (arg == "--interface") {
      auto v = value("--interface");
      if (!v) return std::nullopt;
      options.interface = *v;
    } else if (arg == "--topic") {
      auto v = value("--topic");
      if (!v) return std::nullopt;
      options.topic = *v;
    } else if (arg == "--target") {
      auto v = value("--target");
      if (!v) return std::nullopt;
      options.target = *v;
    } else if (arg == "--listen") {
      auto v = value("--listen");
      if (!v) return std::nullopt;
      options.listen = *v;
    } else if (arg == "--ack-target") {
      auto v = value("--ack-target");
      if (!v) return std::nullopt;
      options.ack_target = *v;
    } else if (arg == "--port") {
      auto v = value("--port");
      if (!v) return std::nullopt;
      options.port = std::stoi(*v);
    } else if (arg == "--ack-port") {
      auto v = value("--ack-port");
      if (!v) return std::nullopt;
      options.ack_port = std::stoi(*v);
    } else if (arg == "--duration") {
      auto v = value("--duration");
      if (!v) return std::nullopt;
      options.duration_sec = std::stoi(*v);
    } else if (arg == "--send-hz") {
      auto v = value("--send-hz");
      if (!v) return std::nullopt;
      options.send_hz = std::stod(*v);
    } else if (arg == "--command-hz") {
      auto v = value("--command-hz");
      if (!v) return std::nullopt;
      options.command_hz = std::stod(*v);
    } else if (arg == "--soft-timeout-ms") {
      auto v = value("--soft-timeout-ms");
      if (!v) return std::nullopt;
      options.soft_timeout_ms = std::stoi(*v);
    } else if (arg == "--hard-timeout-ms" ||
               arg == "--command-timeout-ms") {
      auto v = value(arg.c_str());
      if (!v) return std::nullopt;
      options.hard_timeout_ms = std::stoi(*v);
    } else if (arg == "--axis-deadzone") {
      auto v = value("--axis-deadzone");
      if (!v) return std::nullopt;
      options.axis_calibration.deadzone = std::stof(*v);
    } else if (arg == "--lx-min") {
      auto v = value("--lx-min"); if (!v) return std::nullopt;
      options.axis_calibration.lx.minimum = std::stof(*v);
    } else if (arg == "--lx-center") {
      auto v = value("--lx-center"); if (!v) return std::nullopt;
      options.axis_calibration.lx.center = std::stof(*v);
    } else if (arg == "--lx-max") {
      auto v = value("--lx-max"); if (!v) return std::nullopt;
      options.axis_calibration.lx.maximum = std::stof(*v);
    } else if (arg == "--ly-min") {
      auto v = value("--ly-min"); if (!v) return std::nullopt;
      options.axis_calibration.ly.minimum = std::stof(*v);
    } else if (arg == "--ly-center") {
      auto v = value("--ly-center"); if (!v) return std::nullopt;
      options.axis_calibration.ly.center = std::stof(*v);
    } else if (arg == "--ly-max") {
      auto v = value("--ly-max"); if (!v) return std::nullopt;
      options.axis_calibration.ly.maximum = std::stof(*v);
    } else if (arg == "--rx-min") {
      auto v = value("--rx-min"); if (!v) return std::nullopt;
      options.axis_calibration.rx.minimum = std::stof(*v);
    } else if (arg == "--rx-center") {
      auto v = value("--rx-center"); if (!v) return std::nullopt;
      options.axis_calibration.rx.center = std::stof(*v);
    } else if (arg == "--rx-max") {
      auto v = value("--rx-max"); if (!v) return std::nullopt;
      options.axis_calibration.rx.maximum = std::stof(*v);
    } else if (arg == "--ry-min") {
      auto v = value("--ry-min"); if (!v) return std::nullopt;
      options.axis_calibration.ry.minimum = std::stof(*v);
    } else if (arg == "--ry-center") {
      auto v = value("--ry-center"); if (!v) return std::nullopt;
      options.axis_calibration.ry.center = std::stof(*v);
    } else if (arg == "--ry-max") {
      auto v = value("--ry-max"); if (!v) return std::nullopt;
      options.axis_calibration.ry.maximum = std::stof(*v);
    } else if (arg == "--allowed-source") {
      auto v = value("--allowed-source");
      if (!v) return std::nullopt;
      options.allowed_source = *v;
    } else if (arg == "--enable-robot-command") {
      options.enable_robot_command = true;
    } else if (arg == "--deadman-button") {
      auto v = value("--deadman-button");
      if (!v) return std::nullopt;
      if (*v == "none") {
        options.deadman_button = "none";
        options.deadman_mask = 0;
        continue;
      }
      const auto mask = ButtonMaskByName(*v);
      if (!mask) {
        std::cerr << "Unknown deadman button: " << *v << "\n"
                  << "Supported buttons: "
                  << a2lab::Join(
                         std::vector<std::string>(a2lab::kButtonNames.begin(),
                                                  a2lab::kButtonNames.end()),
                         ",")
                  << "\n";
        return std::nullopt;
      }
      options.deadman_button = *v;
      options.deadman_mask = *mask;
    } else if (arg == "--balance-stand-on-start") {
      options.balance_stand_on_start = true;
    } else if (arg == "--native-button-map") {
      options.native_button_map = true;
    } else if (arg == "--enable-special-actions") {
      options.enable_special_actions = true;
    } else if (arg == "--csv") {
      auto v = value("--csv");
      if (!v) return std::nullopt;
      options.csv = *v;
    } else if (arg == "-h" || arg == "--help") {
      PrintUsage(argv[0]);
      return std::nullopt;
    } else {
      std::cerr << "Unknown argument: " << arg << "\n";
      return std::nullopt;
    }
  }
  if (options.soft_timeout_ms < 50 ||
      options.hard_timeout_ms <= options.soft_timeout_ms) {
    std::cerr << "timeouts require 50 <= soft < hard\n";
    return std::nullopt;
  }
  const auto valid_axis = [](const a2lab::AxisCalibration& axis) {
    return axis.minimum < axis.center && axis.center < axis.maximum;
  };
  if (!valid_axis(options.axis_calibration.lx) ||
      !valid_axis(options.axis_calibration.ly) ||
      !valid_axis(options.axis_calibration.rx) ||
      !valid_axis(options.axis_calibration.ry) ||
      options.axis_calibration.deadzone < 0.0F ||
      options.axis_calibration.deadzone >= 0.95F) {
    std::cerr << "invalid axis calibration or deadzone\n";
    return std::nullopt;
  }
  if (options.enable_robot_command && options.allowed_source.empty() &&
      options.mode != "loopback") {
    std::cerr << "--enable-robot-command requires --allowed-source in receiver mode\n";
    return std::nullopt;
  }
  return options;
}

int MakeUdpSocket() {
  const int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) {
    perror("socket");
  }
  return fd;
}

bool SetNonBlocking(int fd) {
  const int flags = fcntl(fd, F_GETFL, 0);
  return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

std::optional<sockaddr_in> MakeAddress(const std::string& ip, int port) {
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<std::uint16_t>(port));
  if (inet_pton(AF_INET, ip.c_str(), &addr.sin_addr) != 1) {
    std::cerr << "Invalid IPv4 address: " << ip << "\n";
    return std::nullopt;
  }
  return addr;
}

bool BindUdp(int fd, const std::string& ip, int port) {
  const auto addr = MakeAddress(ip, port);
  if (!addr) return false;
  if (::bind(fd, reinterpret_cast<const sockaddr*>(&*addr), sizeof(*addr)) != 0) {
    perror("bind");
    return false;
  }
  return true;
}

struct LatestLowState {
  bool has_sample{false};
  std::uint64_t arrival_steady_ns{0};
  std::uint32_t robot_tick_ms{0};
  a2lab::RemoteState remote;
};

class LowStateCache {
 public:
  void Update(const LowState* low_state) {
    LatestLowState next;
    next.has_sample = true;
    next.arrival_steady_ns = SteadyNs();
    next.robot_tick_ms = low_state->tick();
    next.remote = a2lab::ParseRemote(low_state->wireless_remote());
    std::lock_guard<std::mutex> lock(mutex_);
    latest_ = next;
  }

  LatestLowState Snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return latest_;
  }

 private:
  mutable std::mutex mutex_;
  LatestLowState latest_;
};

class RobotCommandSink {
 public:
  explicit RobotCommandSink(const Options& options)
      : enabled_(options.enable_robot_command),
        deadman_required_(options.deadman_mask != 0U),
        neutral_seen_(options.deadman_mask != 0U),
        native_button_map_(options.native_button_map),
        enable_special_actions_(options.enable_special_actions),
        axis_calibration_(options.axis_calibration) {
    if (!enabled_) {
      return;
    }
    sport_client_ = std::make_unique<unitree::robot::a2::SportClient>();
    sport_client_->SetTimeout(2.0f);
    sport_client_->Init();
    if (options.balance_stand_on_start) {
      const int32_t ret = sport_client_->BalanceStand();
      std::cout << "BalanceStand ret=" << ret << "\n";
    }
  }

  a2lab::AckPacket Apply(const a2lab::CommandPacket& packet,
                         std::uint64_t receiver_arrival_ns,
                         double command_hz,
                         std::uint16_t deadman_mask) {
    a2lab::AckPacket ack;
    ack.seq = packet.seq;
    ack.original_send_steady_ns = packet.send_steady_ns;
    ack.receiver_arrival_steady_ns = receiver_arrival_ns;

    if (!enabled_) {
      ack.ack_send_steady_ns = SteadyNs();
      return ack;
    }

    const auto now = Clock::now();
    const auto limits = a2lab::NativeMotionLimits(gait_mode_, speed_high_);
    const auto motion = (packet.flags & a2lab::kCommandFlagRawAxes) != 0U
        ? a2lab::CalibratedAxesToMotion(packet.lx, packet.ly, packet.rx,
                                        axis_calibration_, limits)
        : packet.command;
    const bool button_changed = packet.buttons != previous_buttons_;
    const bool motion_changed =
        std::fabs(motion.vx - previous_vx_) > 0.0005F ||
        std::fabs(motion.vy - previous_vy_) > 0.0005F ||
        std::fabs(motion.yaw_rate - previous_yaw_) > 0.0005F;
    const bool should_command =
        now >= next_command_time_ || button_changed || motion_changed;
    previous_buttons_ = packet.buttons;
    previous_vx_ = motion.vx;
    previous_vy_ = motion.vy;
    previous_yaw_ = motion.yaw_rate;
    if (!should_command) {
      ack.command_result = last_result_;
      // This flag describes this packet only, not the previous command state.
      ack.flags = 0;
      ack.ack_send_steady_ns = SteadyNs();
      return ack;
    }

    next_command_time_ =
        now + std::chrono::duration_cast<Clock::duration>(
                  std::chrono::duration<double>(1.0 / std::max(1.0, command_hz)));

    // BalanceStand changes the A2 state asynchronously. Defer gait switching
    // instead of issuing SwitchGait in the same instant.
    if (pending_gait_ >= 0 && now >= pending_gait_time_) {
      last_result_ = sport_client_->SwitchGait(pending_gait_);
      std::cout << "native deferred SwitchGait(" << pending_gait_
                << ") ret=" << last_result_ << "\n";
      pending_gait_ = -1;
      motion_enabled_ = last_result_ == 0;
      if (last_result_ == 0) {
        gait_mode_ = pending_gait_mode_;
      }
      last_command_sent_ = false;
      was_moving_ = false;
      ack.command_result = last_result_;
      ack.flags = a2lab::kAckFlagRobotActionSent;
      ack.ack_send_steady_ns = SteadyNs();
      return ack;
    }

    if (native_button_map_) {
      const auto now_ms = static_cast<std::uint64_t>(
          std::chrono::duration_cast<std::chrono::milliseconds>(
              now.time_since_epoch()).count());
      const auto action = button_mapper_.Update(packet.buttons, now_ms);
      if (action) {
        last_result_ = ExecuteAction(*action);
        last_command_sent_ = false;
        was_moving_ = false;
        ack.command_result = last_result_;
        ack.flags = last_action_sent_ ? a2lab::kAckFlagRobotActionSent : 0;
        ack.ack_send_steady_ns = SteadyNs();
        return ack;
      }
    }

    const bool button_held =
        deadman_mask == 0U || (packet.buttons & deadman_mask) != 0U;
    const bool nonzero_motion =
        std::fabs(motion.vx) > 0.0005F ||
        std::fabs(motion.vy) > 0.0005F ||
        std::fabs(motion.yaw_rate) > 0.0005F;
    if (watchdog_latched_) {
      const bool safe_rearm = deadman_required_ ? !button_held : !nonzero_motion;
      if (safe_rearm) {
        watchdog_latched_ = false;
        neutral_seen_ = true;
        last_result_ = sport_client_->StopMove();
      }
      last_command_sent_ = false;
      ack.command_result = last_result_;
      ack.ack_send_steady_ns = SteadyNs();
      return ack;
    }
    if (!deadman_required_ && !neutral_seen_) {
      if (!nonzero_motion) {
        neutral_seen_ = true;
      }
      last_result_ = sport_client_->StopMove();
      last_command_sent_ = false;
    } else if (button_held && nonzero_motion && motion_enabled_) {
      const float vx =
          std::clamp(motion.vx, -limits.max_vx, limits.max_vx);
      const float vy =
          std::clamp(motion.vy, -limits.max_vy, limits.max_vy);
      const float yaw =
          std::clamp(motion.yaw_rate, -limits.max_yaw, limits.max_yaw);
      last_result_ = sport_client_->Move(vx, vy, yaw);
      last_command_sent_ = true;
      was_moving_ = true;
    } else if (motion_enabled_ && was_moving_) {
      // A centered native joystick means zero velocity, not StopMove(). The
      // latter resets gait parameters and would undo running/climbing modes.
      last_result_ = sport_client_->Move(0.0F, 0.0F, 0.0F);
      last_command_sent_ = false;
      was_moving_ = false;
    } else {
      last_command_sent_ = false;
    }
    ack.command_result = last_result_;
    ack.flags = last_command_sent_ ? a2lab::kAckFlagRobotCommandSent : 0;
    ack.ack_send_steady_ns = SteadyNs();
    return ack;
  }

  void SoftWatchdogStop() {
    if (!enabled_ || watchdog_latched_) {
      return;
    }
    last_result_ = sport_client_->Move(0.0F, 0.0F, 0.0F);
    last_command_sent_ = false;
    was_moving_ = false;
    std::cerr << "SOFT WATCHDOG: brief UDP timeout; Move(0,0,0) ret="
              << last_result_ << ". Fresh input resumes immediately.\n";
  }

  void HardWatchdogStop() {
    if (!enabled_ || watchdog_latched_) {
      return;
    }
    last_result_ = sport_client_->StopMove();
    last_command_sent_ = false;
    was_moving_ = false;
    watchdog_latched_ = true;
    neutral_seen_ = false;
    std::cerr << "HARD WATCHDOG: prolonged UDP timeout; StopMove ret="
              << last_result_ << ". Return joystick to neutral before re-enabling.\n";
  }

  void Stop() {
    if (enabled_) {
      const int32_t ret = sport_client_->StopMove();
      std::cout << "final StopMove ret=" << ret << "\n";
    }
  }

 private:
  int32_t ExecuteAction(a2lab::A2Action action) {
    last_action_sent_ = true;
    int32_t ret = 0;
    switch (action) {
      case a2lab::A2Action::Damp:
        pending_gait_ = -1;
        motion_enabled_ = false;
        ret = sport_client_->Damp();
        break;
      case a2lab::A2Action::StandOrLie:
        pending_gait_ = -1;
        motion_enabled_ = false;
        {
          std::map<std::string, std::string> state;
          const int32_t state_ret = sport_client_->GetState(state);
          if (state_ret == 0) {
            const auto it = state.find("fsm_id");
            if (it != state.end()) {
              stand_lie_next_down_ = it->second == "2";
            }
          }
        }
        if (stand_lie_next_down_) {
          ret = sport_client_->StandDown();
        } else {
          ret = sport_client_->StandUp();
        }
        stand_lie_next_down_ = !stand_lie_next_down_;
        break;
      case a2lab::A2Action::DefaultGait:
        pending_gait_ = -1;
        // BalanceStand is the documented "unlock/default gait" operation.
        // Do not immediately follow it with SwitchGait: the transition is
        // asynchronous and the second request can race the state machine.
        ret = sport_client_->BalanceStand();
        motion_enabled_ = ret == 0;
        gait_mode_ = a2lab::A2GaitMode::Walk;
        speed_high_ = false;
        stand_lie_next_down_ = false;
        break;
      case a2lab::A2Action::RunningGait:
        ret = sport_client_->BalanceStand();
        if (ret == 0) {
          pending_gait_ = 1;
          pending_gait_mode_ = a2lab::A2GaitMode::Run;
          pending_gait_time_ = Clock::now() + std::chrono::milliseconds(300);
        }
        motion_enabled_ = false;
        break;
      case a2lab::A2Action::ClimbGait:
        ret = sport_client_->BalanceStand();
        if (ret == 0) {
          pending_gait_ = 2;
          pending_gait_mode_ = a2lab::A2GaitMode::Climb;
          pending_gait_time_ = Clock::now() + std::chrono::milliseconds(300);
        }
        motion_enabled_ = false;
        break;
      case a2lab::A2Action::LeftSideGait:
        ret = sport_client_->LeftSideGait(1);
        motion_enabled_ = true;
        break;
      case a2lab::A2Action::RightSideGait:
        ret = sport_client_->RightSideGait(1);
        motion_enabled_ = true;
        break;
      case a2lab::A2Action::RecoveryStand:
        ret = sport_client_->RecoveryStand();
        motion_enabled_ = false;
        break;
      case a2lab::A2Action::BodyHeightUp:
        body_height_ = std::min(0.50F, body_height_ + 0.02F);
        ret = sport_client_->BodyHeight(body_height_);
        break;
      case a2lab::A2Action::BodyHeightDown:
        body_height_ = std::max(0.30F, body_height_ - 0.02F);
        ret = sport_client_->BodyHeight(body_height_);
        break;
      case a2lab::A2Action::SpeedHigh:
        ret = sport_client_->SpeedLevel(1);
        if (ret == 0) speed_high_ = true;
        break;
      case a2lab::A2Action::SpeedLow:
        ret = sport_client_->SpeedLevel(0);
        if (ret == 0) speed_high_ = false;
        break;
      case a2lab::A2Action::ToggleAutoRecovery:
        {
          std::map<std::string, std::string> state;
          const int32_t state_ret = sport_client_->GetState(state);
          if (state_ret == 0) {
            const auto it = state.find("auto_recovery_switch");
            if (it != state.end()) {
              auto_recovery_enabled_ =
                  it->second == "1" || it->second == "true" ||
                  it->second == "True";
            }
          }
        }
        auto_recovery_enabled_ = !auto_recovery_enabled_;
        ret = sport_client_->SetAutoRecovery(auto_recovery_enabled_ ? 1 : 0);
        break;
      case a2lab::A2Action::FrontFlip:
      case a2lab::A2Action::BackFlip:
      case a2lab::A2Action::HandStand:
      case a2lab::A2Action::BipedStand:
        if (!enable_special_actions_) {
          last_action_sent_ = false;
          std::cerr << "BLOCKED dangerous native action: "
                    << a2lab::A2ActionName(action)
                    << "; start receiver with --enable-special-actions to allow it\n";
          return 0;
        }
        motion_enabled_ = false;
        if (action == a2lab::A2Action::FrontFlip) ret = sport_client_->FrontFlip();
        if (action == a2lab::A2Action::BackFlip) ret = sport_client_->BackFlip();
        if (action == a2lab::A2Action::HandStand) ret = sport_client_->HandStand(1);
        if (action == a2lab::A2Action::BipedStand) ret = sport_client_->BipedStand(1);
        break;
      case a2lab::A2Action::BuzzerToggleUnsupported:
        last_action_sent_ = false;
        std::cerr << "UNSUPPORTED by public A2 SportClient: triple-F1 buzzer toggle\n";
        return 0;
    }
    std::cout << "native action=" << a2lab::A2ActionName(action)
              << " ret=" << ret;
    if (action == a2lab::A2Action::SpeedHigh ||
        action == a2lab::A2Action::SpeedLow) {
      const auto limits = a2lab::NativeMotionLimits(gait_mode_, speed_high_);
      std::cout << " speed=" << (speed_high_ ? "high" : "low")
                << " max(vx,vy,yaw)=" << limits.max_vx << ','
                << limits.max_vy << ',' << limits.max_yaw;
    }
    std::cout << "\n";
    return ret;
  }

  bool enabled_{false};
  bool deadman_required_{true};
  bool neutral_seen_{true};
  std::unique_ptr<unitree::robot::a2::SportClient> sport_client_;
  Clock::time_point next_command_time_{};
  std::uint16_t previous_buttons_{0};
  float previous_vx_{0.0F};
  float previous_vy_{0.0F};
  float previous_yaw_{0.0F};
  int32_t last_result_{0};
  bool last_command_sent_{false};
  bool watchdog_latched_{false};
  bool was_moving_{false};
  bool native_button_map_{false};
  bool enable_special_actions_{false};
  bool last_action_sent_{false};
  bool motion_enabled_{true};
  bool stand_lie_next_down_{false};
  bool auto_recovery_enabled_{true};
  float body_height_{0.40F};
  int pending_gait_{-1};
  Clock::time_point pending_gait_time_{};
  a2lab::A2GaitMode gait_mode_{a2lab::A2GaitMode::Walk};
  a2lab::A2GaitMode pending_gait_mode_{a2lab::A2GaitMode::Walk};
  bool speed_high_{false};
  a2lab::RemoteAxisCalibration axis_calibration_;
  a2lab::A2ButtonMapper button_mapper_;
};

struct ReceivedCommand {
  a2lab::CommandPacket packet;
  std::uint64_t receiver_arrival_ns{0};
  sockaddr_in source{};
};

class AsyncRobotCommandProcessor {
 public:
  AsyncRobotCommandProcessor(const Options& options, int socket_fd)
      : options_(options), socket_fd_(socket_fd), sink_(options),
        worker_(&AsyncRobotCommandProcessor::Run, this) {}

  ~AsyncRobotCommandProcessor() { Stop(); }

  void Enqueue(ReceivedCommand command) {
    std::optional<ReceivedCommand> superseded;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (pending_) {
        if (pending_->packet.buttons != command.packet.buttons) {
          button_edges_.push_back(std::move(*pending_));
        } else {
          superseded = std::move(pending_);
        }
      }
      pending_ = std::move(command);
      last_receive_time_ = Clock::now();
      has_received_ = true;
      soft_timeout_sent_ = false;
      hard_timeout_sent_ = false;
    }
    if (superseded) SendSupersededAck(*superseded);
    condition_.notify_one();
  }

  void Stop() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (stopping_) return;
      stopping_ = true;
      for (const auto& edge : button_edges_) SendSupersededAck(edge);
      button_edges_.clear();
      if (pending_) {
        SendSupersededAck(*pending_);
        pending_.reset();
      }
    }
    condition_.notify_one();
    if (worker_.joinable()) worker_.join();
  }

 private:
  void SendAck(const a2lab::AckPacket& ack, sockaddr_in destination) {
    destination.sin_port = htons(static_cast<std::uint16_t>(options_.ack_port));
    const auto bytes = a2lab::SerializeAck(ack);
    ::sendto(socket_fd_, bytes.data(), bytes.size(), 0,
             reinterpret_cast<const sockaddr*>(&destination),
             sizeof(destination));
  }

  void SendSupersededAck(const ReceivedCommand& command) {
    a2lab::AckPacket ack;
    ack.seq = command.packet.seq;
    ack.original_send_steady_ns = command.packet.send_steady_ns;
    ack.receiver_arrival_steady_ns = command.receiver_arrival_ns;
    ack.ack_send_steady_ns = SteadyNs();
    ack.flags = a2lab::kAckFlagSuperseded;
    SendAck(ack, command.source);
  }

  void Run() {
    const auto soft_timeout =
        std::chrono::milliseconds(options_.soft_timeout_ms);
    const auto hard_timeout =
        std::chrono::milliseconds(options_.hard_timeout_ms);
    while (true) {
      std::optional<ReceivedCommand> command;
      bool soft_stop = false;
      bool hard_stop = false;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        condition_.wait_for(lock, std::chrono::milliseconds(5), [&] {
          return stopping_ || !button_edges_.empty() || pending_.has_value();
        });
        if (stopping_) break;
        if (!button_edges_.empty()) {
          command = std::move(button_edges_.front());
          button_edges_.pop_front();
        } else if (pending_) {
          command = std::move(pending_);
          pending_.reset();
        } else if (has_received_) {
          const auto silence = Clock::now() - last_receive_time_;
          if (silence >= hard_timeout && !hard_timeout_sent_) {
            hard_timeout_sent_ = true;
            soft_timeout_sent_ = true;
            hard_stop = true;
          } else if (silence >= soft_timeout && !soft_timeout_sent_) {
            soft_timeout_sent_ = true;
            soft_stop = true;
          }
        }
      }

      if (command) {
        auto ack = sink_.Apply(command->packet, command->receiver_arrival_ns,
                               options_.command_hz, options_.deadman_mask);
        SendAck(ack, command->source);
      } else if (hard_stop) {
        sink_.HardWatchdogStop();
      } else if (soft_stop) {
        sink_.SoftWatchdogStop();
      }
    }
    sink_.Stop();
  }

  Options options_;
  int socket_fd_{-1};
  RobotCommandSink sink_;
  std::mutex mutex_;
  std::condition_variable condition_;
  std::deque<ReceivedCommand> button_edges_;
  std::optional<ReceivedCommand> pending_;
  Clock::time_point last_receive_time_{};
  bool has_received_{false};
  bool soft_timeout_sent_{false};
  bool hard_timeout_sent_{false};
  bool stopping_{false};
  std::thread worker_;
};

int RunReceiver(const Options& options) {
  const int recv_fd = MakeUdpSocket();
  if (recv_fd < 0) return 1;
  if (!BindUdp(recv_fd, options.listen, options.port)) return 1;
  SetNonBlocking(recv_fd);
  in_addr allowed_source_addr{};
  const bool restrict_source = !options.allowed_source.empty();
  if (restrict_source &&
      ::inet_pton(AF_INET, options.allowed_source.c_str(), &allowed_source_addr) != 1) {
    std::cerr << "Invalid --allowed-source IPv4: " << options.allowed_source << "\n";
    ::close(recv_fd);
    return 1;
  }
  if (options.enable_robot_command) {
    unitree::robot::ChannelFactory::Instance()->Init(0, options.interface);
  }
  AsyncRobotCommandProcessor command_processor(options, recv_fd);

  std::array<std::uint8_t, 2048> buffer{};
  std::uint64_t count = 0;
  std::uint64_t rejected_source = 0;
  std::uint64_t rejected_sequence = 0;
  std::uint64_t last_seq = 0;
  bool has_seq = false;
  auto last_valid_packet = Clock::now();
  const auto hard_timeout = std::chrono::milliseconds(options.hard_timeout_ms);
  const auto receiver_start = Clock::now();
  auto next_print = Clock::now();
  std::cout << "UDP receiver dry-run listening on " << options.listen << ':'
            << options.port << ", ACK -> sender IP:" << options.ack_port
            << "\n";
  if (options.enable_robot_command) {
    if (options.deadman_mask == 0U) {
      std::cout << "ROBOT COMMAND ENABLED: direct joystick mode; neutral is required before arming\n";
    } else {
      std::cout << "ROBOT COMMAND ENABLED: hold " << options.deadman_button
                << " to forward Move; release it to StopMove\n";
    }
    std::cout << "  allowed source: " << options.allowed_source << "\n"
              << "  soft/hard timeout: " << options.soft_timeout_ms << '/'
              << options.hard_timeout_ms << " ms\n"
              << "  raw axis mapping: receiver-owned, calibrated\n";
    if (options.native_button_map) {
      std::cout << "  documented A2 button mapping: enabled\n"
                << "  dangerous special actions: "
                << (options.enable_special_actions ? "enabled" : "blocked") << "\n";
    }
  } else {
    std::cout << "note: receiver only unpacks and prints motion command; no robot command is published\n";
  }

  while (!g_stop.load()) {
    const auto loop_now = Clock::now();
    if (options.duration_sec > 0 && loop_now - receiver_start >=
                                        std::chrono::seconds(options.duration_sec)) {
      break;
    }
    sockaddr_in src{};
    socklen_t src_len = sizeof(src);
    const auto n = ::recvfrom(recv_fd, buffer.data(), buffer.size(), 0,
                              reinterpret_cast<sockaddr*>(&src), &src_len);
    if (n < 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
      continue;
    }
    if (restrict_source && src.sin_addr.s_addr != allowed_source_addr.s_addr) {
      ++rejected_source;
      continue;
    }
    const auto arrival_ns = SteadyNs();
    const auto packet = a2lab::ParseCommand(buffer.data(), static_cast<std::size_t>(n));
    if (!packet) {
      continue;
    }
    if (has_seq && packet->seq <= last_seq) {
      if (loop_now - last_valid_packet < hard_timeout) {
        ++rejected_sequence;
        continue;
      }
      // Permit a sender process to restart sequence numbering only after the
      // previous stream has reached the hard-timeout boundary.
      has_seq = false;
    }
    has_seq = true;
    last_seq = packet->seq;
    last_valid_packet = Clock::now();
    ++count;
    if (count == 1) {
      char source_ip[INET_ADDRSTRLEN]{};
      ::inet_ntop(AF_INET, &src.sin_addr, source_ip, sizeof(source_ip));
      std::cout << "UDP source=" << source_ip << ':' << ntohs(src.sin_port)
                << "\n";
    }
    command_processor.Enqueue({*packet, arrival_ns, src});

    const auto now = Clock::now();
    if (now >= next_print || packet->buttons != 0) {
      next_print = now + std::chrono::milliseconds(500);
      std::cout << "rx seq=" << packet->seq
                << " buttons=" << a2lab::Join(a2lab::PressedButtons(packet->buttons), "+")
                << std::fixed << std::setprecision(3)
                << " axes(lx,ly,rx,ry)=" << packet->lx << ',' << packet->ly
                << ',' << packet->rx << ',' << packet->ry
                << " mode="
                << (((packet->flags & a2lab::kCommandFlagRawAxes) != 0U)
                        ? "raw_axes" : "legacy_velocity")
                << " queued=1"
                << " count=" << count << "\n";
    }
  }

  command_processor.Stop();
  ::close(recv_fd);
  std::cout << "receiver summary: received=" << count
            << " rejected_source=" << rejected_source
            << " rejected_sequence=" << rejected_sequence << "\n";
  return 0;
}

struct PendingPacket {
  std::uint64_t send_steady_ns{0};
  std::uint64_t lowstate_arrival_steady_ns{0};
  a2lab::CommandPacket packet;
};

int RunSender(const Options& options) {
  const int send_fd = MakeUdpSocket();
  const int ack_fd = MakeUdpSocket();
  if (send_fd < 0 || ack_fd < 0) return 1;
  if (!BindUdp(ack_fd, "0.0.0.0", options.ack_port)) return 1;
  SetNonBlocking(ack_fd);
  const auto target_addr = MakeAddress(options.target, options.port);
  if (!target_addr) return 1;

  std::filesystem::create_directories(std::filesystem::path(options.csv).parent_path());
  std::ofstream csv(options.csv);
  if (!csv) {
    std::cerr << "Failed to open CSV: " << options.csv << "\n";
    return 1;
  }
  csv << "seq,host_unix_ns,send_steady_ns,lowstate_arrival_steady_ns,"
      << "robot_tick_ms,ack_arrival_steady_ns,rtt_ms,lowstate_to_ack_ms,"
      << "receiver_oneway_ms_same_clock,ack_result,ack_flags,robot_command_sent,"
      << "buttons,pressed,lx,ly,rx,ry,vx,vy,yaw_rate\n";

  LowStateCache cache;
  unitree::robot::ChannelFactory::Instance()->Init(0, options.interface);
  unitree::robot::ChannelSubscriber<LowState> subscriber(options.topic);
  subscriber.InitChannel(
      [&cache](const void* message) {
        cache.Update(static_cast<const LowState*>(message));
      },
      0);

  std::unordered_map<std::uint64_t, PendingPacket> pending;
  std::array<std::uint8_t, 2048> ack_buffer{};
  std::uint64_t seq = 0;
  std::uint64_t sent = 0;
  std::uint64_t acked = 0;
  auto start = Clock::now();
  auto next_send = Clock::now();
  auto next_print = Clock::now();
  const auto send_period =
      std::chrono::duration_cast<Clock::duration>(
          std::chrono::duration<double>(1.0 / options.send_hz));

  std::cout << "UDP sender dry-run\n"
            << "  DDS interface: " << options.interface << "\n"
            << "  DDS topic: " << options.topic << "\n"
            << "  UDP target: " << options.target << ':' << options.port << "\n"
            << "  ACK listen port: " << options.ack_port << "\n"
            << "  CSV: " << options.csv << "\n";

  while (!g_stop.load()) {
    const auto now = Clock::now();
    if (options.duration_sec > 0 &&
        std::chrono::duration_cast<std::chrono::seconds>(now - start).count() >=
            options.duration_sec) {
      break;
    }

    sockaddr_in src{};
    socklen_t src_len = sizeof(src);
    while (true) {
      const auto n = ::recvfrom(ack_fd, ack_buffer.data(), ack_buffer.size(), 0,
                                reinterpret_cast<sockaddr*>(&src), &src_len);
      if (n < 0) break;
      const auto ack_arrival_ns = SteadyNs();
      const auto ack = a2lab::ParseAck(ack_buffer.data(), static_cast<std::size_t>(n));
      if (!ack) continue;
      const auto it = pending.find(ack->seq);
      if (it == pending.end()) continue;
      const auto& p = it->second;
      const double rtt_ms = NsToMs(ack_arrival_ns - p.send_steady_ns);
      const double lowstate_to_ack_ms =
          NsToMs(ack_arrival_ns - p.lowstate_arrival_steady_ns);
      const double receiver_oneway_ms =
          ack->receiver_arrival_steady_ns >= p.send_steady_ns
              ? NsToMs(ack->receiver_arrival_steady_ns - p.send_steady_ns)
              : 0.0;
      csv << p.packet.seq << ',' << UnixNs() << ',' << p.send_steady_ns << ','
          << p.lowstate_arrival_steady_ns << ',' << p.packet.robot_tick_ms << ','
          << ack_arrival_ns << ',' << std::fixed << std::setprecision(6)
          << rtt_ms << ',' << lowstate_to_ack_ms << ','
          << receiver_oneway_ms << ',' << ack->command_result << ','
          << ack->flags << ','
          << ((ack->flags & a2lab::kAckFlagRobotCommandSent) ? 1 : 0)
          << ",0x" << std::hex << std::setw(4)
          << std::setfill('0') << p.packet.buttons << std::dec << ','
          << '"' << a2lab::Join(a2lab::PressedButtons(p.packet.buttons), "+")
          << '"' << ',' << p.packet.lx << ',' << p.packet.ly << ','
          << p.packet.rx << ',' << p.packet.ry << ',' << p.packet.command.vx
          << ',' << p.packet.command.vy << ',' << p.packet.command.yaw_rate
          << '\n';
      pending.erase(it);
      ++acked;
    }

    if (now >= next_send) {
      next_send = now + send_period;
      const auto latest = cache.Snapshot();
      if (latest.has_sample) {
        a2lab::CommandPacket packet;
        packet.seq = ++seq;
        packet.send_steady_ns = SteadyNs();
        packet.lowstate_arrival_steady_ns = latest.arrival_steady_ns;
        packet.robot_tick_ms = latest.robot_tick_ms;
        packet.buttons = latest.remote.buttons;
        packet.lx = latest.remote.lx;
        packet.ly = latest.remote.ly;
        packet.rx = latest.remote.rx;
        packet.ry = latest.remote.ry;
        packet.command = a2lab::RemoteToMotionCommand(latest.remote);
        const auto bytes = a2lab::SerializeCommand(packet);
        ::sendto(send_fd, bytes.data(), bytes.size(), 0,
                 reinterpret_cast<const sockaddr*>(&*target_addr),
                 sizeof(*target_addr));
        PendingPacket pending_packet;
        pending_packet.send_steady_ns = packet.send_steady_ns;
        pending_packet.lowstate_arrival_steady_ns = latest.arrival_steady_ns;
        pending_packet.packet = packet;
        pending[packet.seq] = pending_packet;
        ++sent;
      }
    }

    if (now >= next_print) {
      next_print = now + std::chrono::milliseconds(500);
      std::cout << "sent=" << sent << " acked=" << acked
                << " pending=" << pending.size() << "\n";
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }

  subscriber.CloseChannel();
  ::close(send_fd);
  ::close(ack_fd);
  std::cout << "sender summary: sent=" << sent << " acked=" << acked
            << " pending=" << pending.size() << "\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  const auto options = ParseArgs(argc, argv);
  if (!options) return 2;
  std::signal(SIGINT, SignalHandler);
  std::signal(SIGTERM, SignalHandler);

  if (options->mode == "receiver") {
    return RunReceiver(*options);
  }
  if (options->mode == "sender") {
    return RunSender(*options);
  }
  if (options->mode == "loopback") {
    Options receiver_options = *options;
    receiver_options.mode = "receiver";
    receiver_options.listen = "0.0.0.0";
    receiver_options.ack_target = "127.0.0.1";
    std::thread receiver_thread([&receiver_options]() {
      RunReceiver(receiver_options);
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    Options sender_options = *options;
    sender_options.mode = "sender";
    sender_options.target = "127.0.0.1";
    const int result = RunSender(sender_options);
    g_stop.store(true);
    receiver_thread.join();
    return result;
  }

  std::cerr << "Unknown mode: " << options->mode << "\n";
  return 2;
}
