#include <unitree/robot/b2/motion_switcher/motion_switcher_client.hpp>
#include <unitree/robot/channel/channel_factory.hpp>

#include <chrono>
#include <iostream>
#include <string>
#include <thread>

namespace {

std::string ServiceName(const std::string& form, const std::string& name) {
  if (form == "0") {
    if (name == "normal") return "sport_mode";
    if (name == "ai") return "ai_sport";
    if (name == "advanced") return "advanced_sport";
  } else {
    if (name == "ai-w") return "wheeled_sport(go2W)";
    if (name == "normal-w") return "wheeled_sport(b2W)";
  }
  if (name.empty()) return "(none)";
  return name;
}

bool Check(unitree::robot::b2::MotionSwitcherClient& client) {
  std::string form;
  std::string name;
  const int32_t ret = client.CheckMode(form, name);
  std::cout << "CheckMode ret=" << ret << " form=\"" << form << "\" name=\""
            << name << "\" service=\"" << ServiceName(form, name) << "\"\n";
  if (ret != 0) {
    return false;
  }
  if (name.empty()) {
    std::cout << "motion service status: released / inactive\n";
  } else {
    std::cout << "motion service status: active\n";
  }
  return name.empty();
}

void Usage(const char* argv0) {
  std::cerr << "Usage:\n"
            << "  " << argv0 << " <interface> check\n"
            << "  " << argv0 << " <interface> release\n"
            << "  " << argv0 << " <interface> select <mode>\n"
            << "  " << argv0 << " <interface> silent-get\n"
            << "  " << argv0 << " <interface> silent-on\n"
            << "  " << argv0 << " <interface> silent-off\n"
            << "\n"
            << "Examples:\n"
            << "  " << argv0 << " eth0 check\n"
            << "  " << argv0 << " eth0 release\n"
            << "  " << argv0 << " eth0 select ai\n"
            << "  " << argv0 << " eth0 silent-on\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    Usage(argv[0]);
    return 1;
  }

  const std::string interface = argv[1];
  const std::string command = argv[2];
  if (command != "check" && command != "release" && command != "select" &&
      command != "silent-get" && command != "silent-on" &&
      command != "silent-off") {
    Usage(argv[0]);
    return 1;
  }
  if (command == "select" && argc != 4) {
    Usage(argv[0]);
    return 1;
  }

  unitree::robot::ChannelFactory::Instance()->Init(0, interface);

  unitree::robot::b2::MotionSwitcherClient client;
  client.SetTimeout(10.0f);
  client.Init();

  if (command == "check") {
    return Check(client) ? 0 : 2;
  }

  if (command == "silent-get") {
    bool silent = false;
    const int32_t ret = client.GetSilent(silent);
    std::cout << "GetSilent ret=" << ret << " silent=" << (silent ? "true" : "false")
              << "\n";
    return ret == 0 ? 0 : 4;
  }

  if (command == "silent-on" || command == "silent-off") {
    const bool silent = command == "silent-on";
    const int32_t ret = client.SetSilent(silent);
    std::cout << "SetSilent(" << (silent ? "true" : "false") << ") ret=" << ret
              << "\n";
    bool now_silent = false;
    const int32_t get_ret = client.GetSilent(now_silent);
    std::cout << "GetSilent ret=" << get_ret
              << " silent=" << (now_silent ? "true" : "false") << "\n";
    return ret == 0 && get_ret == 0 ? 0 : 4;
  }

  if (command == "select") {
    const std::string mode = argv[3];
    std::cout << "Before select:\n";
    Check(client);
    const int32_t ret = client.SelectMode(mode);
    std::cout << "SelectMode(\"" << mode << "\") ret=" << ret << "\n";
    std::this_thread::sleep_for(std::chrono::seconds(1));
    Check(client);
    return ret == 0 ? 0 : 5;
  }

  std::cout << "Before release:\n";
  Check(client);

  for (int i = 1; i <= 3; ++i) {
    std::cout << "ReleaseMode attempt " << i << "...\n";
    const int32_t ret = client.ReleaseMode();
    std::cout << "ReleaseMode ret=" << ret << "\n";
    std::this_thread::sleep_for(std::chrono::seconds(1));
    if (Check(client)) {
      std::cout << "release result: success\n";
      return 0;
    }
  }

  std::cout << "release result: not released\n";
  return 3;
}
