#include "a2_button_mapper.hpp"

namespace a2lab {
namespace {

constexpr std::uint16_t R1 = 1U << 0U;
constexpr std::uint16_t L1 = 1U << 1U;
constexpr std::uint16_t Start = 1U << 2U;
constexpr std::uint16_t R2 = 1U << 4U;
constexpr std::uint16_t L2 = 1U << 5U;
constexpr std::uint16_t F1 = 1U << 6U;
constexpr std::uint16_t A = 1U << 8U;
constexpr std::uint16_t B = 1U << 9U;
constexpr std::uint16_t X = 1U << 10U;
constexpr std::uint16_t Y = 1U << 11U;
constexpr std::uint16_t Up = 1U << 12U;
constexpr std::uint16_t Down = 1U << 14U;
constexpr std::uint64_t kMultiClickWindowMs = 450;

}  // namespace

const char* A2ActionName(A2Action action) {
  switch (action) {
    case A2Action::Damp: return "L2+B Damp";
    case A2Action::StandOrLie: return "L2+A Stand/Lie";
    case A2Action::DefaultGait: return "Start DefaultGait";
    case A2Action::RunningGait: return "L2+Start RunningGait";
    case A2Action::LeftSideGait: return "double-X LeftSideGait";
    case A2Action::RightSideGait: return "double-Y RightSideGait";
    case A2Action::HandStand: return "double-R1 HandStand";
    case A2Action::BipedStand: return "double-R2 BipedStand";
    case A2Action::RecoveryStand: return "L2+X RecoveryStand";
    case A2Action::ClimbGait: return "R1+X ClimbGait";
    case A2Action::FrontFlip: return "L1+X FrontFlip";
    case A2Action::BackFlip: return "L1+Y BackFlip";
    case A2Action::BodyHeightUp: return "L1+Up BodyHeightUp";
    case A2Action::BodyHeightDown: return "L1+Down BodyHeightDown";
    case A2Action::SpeedHigh: return "Up SpeedHigh";
    case A2Action::SpeedLow: return "Down SpeedLow";
    case A2Action::ToggleAutoRecovery: return "Y+B ToggleAutoRecovery";
    case A2Action::BuzzerToggleUnsupported: return "triple-F1 BuzzerToggle";
  }
  return "Unknown";
}

bool A2ButtonMapper::IsRising(std::uint16_t mask,
                              std::uint16_t buttons) const {
  return (buttons & mask) == mask && (previous_buttons_ & mask) != mask;
}

bool A2ButtonMapper::Click(std::uint16_t bit, std::uint64_t now_ms,
                           int required_clicks) {
  std::uint64_t* last = nullptr;
  int* clicks = nullptr;
  if (bit == X) { last = &last_x_ms_; clicks = &x_clicks_; }
  if (bit == Y) { last = &last_y_ms_; clicks = &y_clicks_; }
  if (bit == R1) { last = &last_r1_ms_; clicks = &r1_clicks_; }
  if (bit == R2) { last = &last_r2_ms_; clicks = &r2_clicks_; }
  if (bit == F1) { last = &last_f1_ms_; clicks = &f1_clicks_; }
  if (!last || !clicks) return false;
  if (*last == 0 || now_ms - *last > kMultiClickWindowMs) *clicks = 0;
  *last = now_ms;
  ++*clicks;
  if (*clicks >= required_clicks) {
    *clicks = 0;
    return true;
  }
  return false;
}

std::optional<A2Action> A2ButtonMapper::Update(std::uint16_t buttons,
                                               std::uint64_t now_ms) {
  const std::uint16_t rising = buttons & ~previous_buttons_;
  std::optional<A2Action> action;

  // Modifier combinations have priority over the single/double-click rules.
  if (rising && IsRising(L2 | B, buttons)) action = A2Action::Damp;
  else if (rising && IsRising(L2 | A, buttons)) action = A2Action::StandOrLie;
  else if (rising && IsRising(L2 | Start, buttons)) action = A2Action::RunningGait;
  else if (rising && IsRising(L2 | X, buttons)) action = A2Action::RecoveryStand;
  else if (rising && IsRising(R1 | X, buttons)) action = A2Action::ClimbGait;
  else if (rising && IsRising(L1 | X, buttons)) action = A2Action::FrontFlip;
  else if (rising && IsRising(L1 | Y, buttons)) action = A2Action::BackFlip;
  else if (rising && IsRising(L1 | Up, buttons)) action = A2Action::BodyHeightUp;
  else if (rising && IsRising(L1 | Down, buttons)) action = A2Action::BodyHeightDown;
  else if (rising && IsRising(Y | B, buttons)) action = A2Action::ToggleAutoRecovery;
  else if ((rising & Start) && !(buttons & L2)) action = A2Action::DefaultGait;
  else if ((rising & Up) && !(buttons & L1)) action = A2Action::SpeedHigh;
  else if ((rising & Down) && !(buttons & L1)) action = A2Action::SpeedLow;
  else if ((rising & X) && !(buttons & (L1 | L2 | R1)) &&
           Click(X, now_ms, 2)) action = A2Action::LeftSideGait;
  else if ((rising & Y) && !(buttons & (L1 | L2 | B)) &&
           Click(Y, now_ms, 2)) action = A2Action::RightSideGait;
  else if ((rising & R1) && !(buttons & X) && Click(R1, now_ms, 2))
    action = A2Action::HandStand;
  else if ((rising & R2) && Click(R2, now_ms, 2))
    action = A2Action::BipedStand;
  else if ((rising & F1) && Click(F1, now_ms, 3))
    action = A2Action::BuzzerToggleUnsupported;

  previous_buttons_ = buttons;
  return action;
}

}  // namespace a2lab
