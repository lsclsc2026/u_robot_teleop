#include "a2_button_mapper.hpp"

#include <cstdint>
#include <iostream>

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

#define CHECK(condition) do { if (!(condition)) {                         \
  std::cerr << "check failed line " << __LINE__ << ": " #condition     \
            << '\n'; return 1; } } while (false)

bool Press(a2lab::A2ButtonMapper& mapper, std::uint16_t buttons,
           std::uint64_t ms, a2lab::A2Action expected) {
  const auto action = mapper.Update(buttons, ms);
  mapper.Update(0, ms + 10);
  return action && *action == expected;
}
}  // namespace

int main() {
  a2lab::A2ButtonMapper mapper;
  CHECK(Press(mapper, L2 | B, 100, a2lab::A2Action::Damp));
  CHECK(Press(mapper, L2 | A, 200, a2lab::A2Action::StandOrLie));
  CHECK(Press(mapper, Start, 300, a2lab::A2Action::DefaultGait));
  CHECK(Press(mapper, L2 | Start, 400, a2lab::A2Action::RunningGait));
  CHECK(Press(mapper, L2 | X, 500, a2lab::A2Action::RecoveryStand));
  CHECK(Press(mapper, R1 | X, 600, a2lab::A2Action::ClimbGait));
  CHECK(Press(mapper, L1 | X, 700, a2lab::A2Action::FrontFlip));
  CHECK(Press(mapper, L1 | Y, 800, a2lab::A2Action::BackFlip));
  CHECK(Press(mapper, L1 | Up, 900, a2lab::A2Action::BodyHeightUp));
  CHECK(Press(mapper, L1 | Down, 1000, a2lab::A2Action::BodyHeightDown));
  CHECK(Press(mapper, Y | B, 1100, a2lab::A2Action::ToggleAutoRecovery));
  CHECK(Press(mapper, Up, 1200, a2lab::A2Action::SpeedHigh));
  CHECK(Press(mapper, Down, 1300, a2lab::A2Action::SpeedLow));

  CHECK(!mapper.Update(X, 2000)); mapper.Update(0, 2010);
  CHECK(Press(mapper, X, 2200, a2lab::A2Action::LeftSideGait));
  CHECK(!mapper.Update(Y, 3000)); mapper.Update(0, 3010);
  CHECK(Press(mapper, Y, 3200, a2lab::A2Action::RightSideGait));
  CHECK(!mapper.Update(R1, 4000)); mapper.Update(0, 4010);
  CHECK(Press(mapper, R1, 4200, a2lab::A2Action::HandStand));
  CHECK(!mapper.Update(R2, 5000)); mapper.Update(0, 5010);
  CHECK(Press(mapper, R2, 5200, a2lab::A2Action::BipedStand));
  CHECK(!mapper.Update(F1, 6000)); mapper.Update(0, 6010);
  CHECK(!mapper.Update(F1, 6150)); mapper.Update(0, 6160);
  CHECK(Press(mapper, F1, 6300, a2lab::A2Action::BuzzerToggleUnsupported));

  std::cout << "A2 button mapper tests passed\n";
  return 0;
}
