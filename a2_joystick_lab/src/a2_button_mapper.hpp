#pragma once

#include <cstdint>
#include <optional>

namespace a2lab {

enum class A2Action {
  Damp,
  StandOrLie,
  DefaultGait,
  RunningGait,
  LeftSideGait,
  RightSideGait,
  HandStand,
  BipedStand,
  RecoveryStand,
  ClimbGait,
  FrontFlip,
  BackFlip,
  BodyHeightUp,
  BodyHeightDown,
  SpeedHigh,
  SpeedLow,
  ToggleAutoRecovery,
  BuzzerToggleUnsupported,
};

const char* A2ActionName(A2Action action);

class A2ButtonMapper {
 public:
  // now_ms must be monotonic. An action is emitted only on a new press edge.
  std::optional<A2Action> Update(std::uint16_t buttons,
                                 std::uint64_t now_ms);

 private:
  bool IsRising(std::uint16_t mask, std::uint16_t buttons) const;
  bool Click(std::uint16_t bit, std::uint64_t now_ms, int required_clicks);

  std::uint16_t previous_buttons_{0};
  std::uint64_t last_x_ms_{0};
  std::uint64_t last_y_ms_{0};
  std::uint64_t last_r1_ms_{0};
  std::uint64_t last_r2_ms_{0};
  std::uint64_t last_f1_ms_{0};
  int x_clicks_{0};
  int y_clicks_{0};
  int r1_clicks_{0};
  int r2_clicks_{0};
  int f1_clicks_{0};
};

}  // namespace a2lab
