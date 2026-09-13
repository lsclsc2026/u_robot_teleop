#include "joystick_protocol.hpp"

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <ctime>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

using LowState = unitree_hg::msg::dds_::LowState_;
using Clock = std::chrono::steady_clock;

std::atomic_bool g_stop{false};

void SignalHandler(int) {
  g_stop.store(true);
}

double SteadyMs(Clock::time_point now) {
  return std::chrono::duration<double, std::milli>(now.time_since_epoch()).count();
}

std::uint64_t SystemNs() {
  const auto now = std::chrono::system_clock::now().time_since_epoch();
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(now).count());
}

std::string TimestampForFile() {
  const auto now = std::chrono::system_clock::now();
  const std::time_t time = std::chrono::system_clock::to_time_t(now);
  std::tm tm{};
  localtime_r(&time, &tm);
  std::ostringstream out;
  out << std::put_time(&tm, "%Y%m%d_%H%M%S");
  return out.str();
}

std::string CsvEscape(const std::string& value) {
  std::string escaped;
  escaped.reserve(value.size() + 2);
  escaped.push_back('"');
  for (const char ch : value) {
    if (ch == '"') {
      escaped.push_back('"');
    }
    escaped.push_back(ch);
  }
  escaped.push_back('"');
  return escaped;
}

double Percentile(std::vector<double> values, double percentile) {
  if (values.empty()) {
    return 0.0;
  }
  std::sort(values.begin(), values.end());
  const double index = percentile * static_cast<double>(values.size() - 1);
  const auto lo = static_cast<std::size_t>(std::floor(index));
  const auto hi = static_cast<std::size_t>(std::ceil(index));
  const double fraction = index - static_cast<double>(lo);
  return values[lo] * (1.0 - fraction) + values[hi] * fraction;
}

struct Options {
  std::string interface;
  std::string topic = "rt/lowstate";
  int duration_sec = 30;
  double print_hz = 2.0;
  std::string csv_path;
  bool csv_enabled = true;
};

void PrintUsage(const char* argv0) {
  std::cerr
      << "Usage: " << argv0 << " <network-interface> [options]\n"
      << "\n"
      << "Options:\n"
      << "  --topic <name>       DDS topic, default rt/lowstate\n"
      << "  --duration <sec>     Run time, default 30. Use 0 for Ctrl-C only\n"
      << "  --csv <path>         CSV output path\n"
      << "  --no-csv             Do not write CSV\n"
      << "  --print-hz <hz>      Console update rate, default 2\n";
}

std::optional<Options> ParseArgs(int argc, char** argv) {
  if (argc < 2) {
    PrintUsage(argv[0]);
    return std::nullopt;
  }

  Options options;
  options.interface = argv[1];
  for (int i = 2; i < argc; ++i) {
    const std::string arg = argv[i];
    auto require_value = [&](const char* name) -> std::optional<std::string> {
      if (i + 1 >= argc) {
        std::cerr << "Missing value for " << name << "\n";
        return std::nullopt;
      }
      return std::string(argv[++i]);
    };

    if (arg == "--topic") {
      const auto value = require_value("--topic");
      if (!value) return std::nullopt;
      options.topic = *value;
    } else if (arg == "--duration") {
      const auto value = require_value("--duration");
      if (!value) return std::nullopt;
      options.duration_sec = std::stoi(*value);
    } else if (arg == "--csv") {
      const auto value = require_value("--csv");
      if (!value) return std::nullopt;
      options.csv_path = *value;
      options.csv_enabled = true;
    } else if (arg == "--no-csv") {
      options.csv_enabled = false;
    } else if (arg == "--print-hz") {
      const auto value = require_value("--print-hz");
      if (!value) return std::nullopt;
      options.print_hz = std::stod(*value);
    } else if (arg == "--help" || arg == "-h") {
      PrintUsage(argv[0]);
      return std::nullopt;
    } else {
      std::cerr << "Unknown argument: " << arg << "\n";
      return std::nullopt;
    }
  }

  if (options.print_hz <= 0.0) {
    options.print_hz = 2.0;
  }
  if (options.csv_enabled && options.csv_path.empty()) {
    options.csv_path = "logs/joystick_" + TimestampForFile() + ".csv";
  }
  return options;
}

struct LatestState {
  std::uint64_t seq{0};
  a2lab::RemoteState remote;
  std::uint16_t previous_buttons{0};
  std::vector<std::string> pressed_edges;
  std::vector<std::string> released_edges;
  a2lab::TickObservation tick;
  double interarrival_ms{0.0};
  double parse_us{0.0};
  bool raw_changed{false};
  bool has_sample{false};
  Clock::time_point last_arrival{};
};

class Monitor {
 public:
  explicit Monitor(std::ofstream* csv) : csv_(csv) {
    if (csv_) {
      *csv_ << "seq,host_unix_ns,host_steady_ms,robot_tick_raw_ms,"
            << "robot_tick_unwrapped_ms,interarrival_ms,tick_delta_ms,"
            << "excess_delay_ms,parse_us,raw_changed,buttons_hex,pressed,"
            << "pressed_edges,released_edges,lx,ly,rx,ry,raw_hex\n";
    }
  }

  void OnLowState(const void* message) {
    const auto arrival = Clock::now();
    const auto* low_state = static_cast<const LowState*>(message);
    const auto parse_start = Clock::now();
    const auto raw = low_state->wireless_remote();
    const auto remote = a2lab::ParseRemote(raw);
    const auto parse_end = Clock::now();

    std::lock_guard<std::mutex> lock(mutex_);
    LatestState item;
    item.seq = ++seq_;
    item.remote = remote;
    item.previous_buttons = latest_.remote.buttons;
    item.raw_changed = !latest_.has_sample || raw != last_raw_;
    item.has_sample = true;
    item.last_arrival = arrival;
    item.parse_us =
        std::chrono::duration<double, std::micro>(parse_end - parse_start).count();
    if (latest_.has_sample) {
      item.interarrival_ms =
          std::chrono::duration<double, std::milli>(arrival - latest_.last_arrival)
              .count();
      interarrival_samples_.push_back(item.interarrival_ms);
    }
    item.tick = latency_.Observe(low_state->tick(), SteadyMs(arrival));
    delay_samples_.push_back(item.tick.excess_delay_ms);
    parse_samples_.push_back(item.parse_us);

    const auto pressed_mask =
        static_cast<std::uint16_t>(remote.buttons & ~item.previous_buttons);
    const auto released_mask =
        static_cast<std::uint16_t>(~remote.buttons & item.previous_buttons);
    item.pressed_edges = a2lab::PressedButtons(pressed_mask);
    item.released_edges = a2lab::PressedButtons(released_mask);

    latest_ = item;
    last_raw_ = raw;
    TrimSamples();
    WriteCsv(item, low_state->tick(), raw);
  }

  LatestState Snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return latest_;
  }

  std::uint64_t Count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return seq_;
  }

  void PrintSummary() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::cout << "\nSummary\n"
              << "  samples: " << seq_ << "\n"
              << "  interarrival ms p50/p95/p99: "
              << Percentile(Copy(interarrival_samples_), 0.50) << " / "
              << Percentile(Copy(interarrival_samples_), 0.95) << " / "
              << Percentile(Copy(interarrival_samples_), 0.99) << "\n"
              << "  relative delay ms p50/p95/p99: "
              << Percentile(Copy(delay_samples_), 0.50) << " / "
              << Percentile(Copy(delay_samples_), 0.95) << " / "
              << Percentile(Copy(delay_samples_), 0.99) << "\n"
              << "  parse us p50/p95/p99: "
              << Percentile(Copy(parse_samples_), 0.50) << " / "
              << Percentile(Copy(parse_samples_), 0.95) << " / "
              << Percentile(Copy(parse_samples_), 0.99) << "\n";
  }

 private:
  static std::vector<double> Copy(const std::deque<double>& input) {
    return std::vector<double>(input.begin(), input.end());
  }

  void TrimSamples() {
    constexpr std::size_t kMaxSamples = 100000;
    while (interarrival_samples_.size() > kMaxSamples) interarrival_samples_.pop_front();
    while (delay_samples_.size() > kMaxSamples) delay_samples_.pop_front();
    while (parse_samples_.size() > kMaxSamples) parse_samples_.pop_front();
  }

  void WriteCsv(const LatestState& item, std::uint32_t raw_tick,
                const std::array<std::uint8_t, 40>& raw) {
    if (!csv_) {
      return;
    }
    std::ostringstream buttons_hex;
    buttons_hex << "0x" << std::hex << std::setw(4) << std::setfill('0')
                << item.remote.buttons;

    *csv_ << item.seq << ',' << SystemNs() << ',' << std::fixed
          << std::setprecision(3) << SteadyMs(item.last_arrival) << ','
          << raw_tick << ',' << item.tick.unwrapped_tick_ms << ','
          << item.interarrival_ms << ',' << item.tick.tick_delta_ms << ','
          << item.tick.excess_delay_ms << ',' << std::setprecision(6)
          << item.parse_us << ',' << (item.raw_changed ? 1 : 0) << ','
          << buttons_hex.str() << ','
          << CsvEscape(a2lab::Join(a2lab::PressedButtons(item.remote.buttons), "+"))
          << ',' << CsvEscape(a2lab::Join(item.pressed_edges, "+")) << ','
          << CsvEscape(a2lab::Join(item.released_edges, "+")) << ','
          << item.remote.lx << ',' << item.remote.ly << ',' << item.remote.rx
          << ',' << item.remote.ry << ',' << a2lab::RawHex(raw) << '\n';
  }

  mutable std::mutex mutex_;
  std::ofstream* csv_{nullptr};
  std::uint64_t seq_{0};
  LatestState latest_;
  std::array<std::uint8_t, 40> last_raw_{};
  a2lab::TickLatencyEstimator latency_;
  std::deque<double> interarrival_samples_;
  std::deque<double> delay_samples_;
  std::deque<double> parse_samples_;
};

}  // namespace

int main(int argc, char** argv) {
  const auto options = ParseArgs(argc, argv);
  if (!options) {
    return 2;
  }

  std::signal(SIGINT, SignalHandler);
  std::signal(SIGTERM, SignalHandler);

  std::ofstream csv;
  if (options->csv_enabled) {
    const std::filesystem::path csv_path(options->csv_path);
    if (csv_path.has_parent_path()) {
      std::filesystem::create_directories(csv_path.parent_path());
    }
    csv.open(csv_path);
    if (!csv) {
      std::cerr << "Failed to open CSV path: " << options->csv_path << "\n";
      return 1;
    }
  }

  Monitor monitor(options->csv_enabled ? &csv : nullptr);

  std::cout << "A2 joystick monitor\n"
            << "  interface: " << options->interface << "\n"
            << "  topic: " << options->topic << "\n"
            << "  csv: "
            << (options->csv_enabled ? options->csv_path : std::string("(disabled)"))
            << "\n"
            << "  note: read-only subscriber; no lowcmd/api command is published\n";

  unitree::robot::ChannelFactory::Instance()->Init(0, options->interface);
  unitree::robot::ChannelSubscriber<LowState> subscriber(options->topic);
  subscriber.InitChannel(
      [&monitor](const void* message) {
        monitor.OnLowState(message);
      },
      0);

  const auto start = Clock::now();
  auto next_print = start;
  std::uint64_t last_print_count = 0;
  bool no_sample_warning_printed = false;
  const auto print_period =
      std::chrono::duration<double>(1.0 / options->print_hz);

  while (!g_stop.load()) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    const auto now = Clock::now();
    if (options->duration_sec > 0 &&
        std::chrono::duration_cast<std::chrono::seconds>(now - start).count() >=
            options->duration_sec) {
      break;
    }

    if (!no_sample_warning_printed &&
        std::chrono::duration_cast<std::chrono::seconds>(now - start).count() >= 3 &&
        monitor.Count() == 0) {
      std::cerr << "No samples yet. Check interface/IP, A2 connection, DDS firewall, "
                   "and whether the robot basic service is running.\n";
      no_sample_warning_printed = true;
    }

    if (now < next_print) {
      continue;
    }
    next_print = now + std::chrono::duration_cast<Clock::duration>(print_period);

    const auto latest = monitor.Snapshot();
    const auto count = monitor.Count();
    const double elapsed =
        std::chrono::duration<double>(now - start).count();
    const double total_hz = elapsed > 0.0 ? static_cast<double>(count) / elapsed : 0.0;
    const double instant_hz =
        static_cast<double>(count - last_print_count) * options->print_hz;
    last_print_count = count;

    if (!latest.has_sample) {
      std::cout << "waiting for lowstate... total_hz=" << total_hz << "\n";
      continue;
    }

    std::cout << std::fixed << std::setprecision(3)
              << "seq=" << latest.seq << " hz=" << total_hz
              << " inst_hz=" << instant_hz
              << " buttons=" << a2lab::Join(a2lab::PressedButtons(latest.remote.buttons), "+")
              << " edges=+" << a2lab::Join(latest.pressed_edges, "+")
              << " -" << a2lab::Join(latest.released_edges, "+")
              << " lx=" << latest.remote.lx << " ly=" << latest.remote.ly
              << " rx=" << latest.remote.rx << " ry=" << latest.remote.ry
              << " inter_ms=" << latest.interarrival_ms
              << " rel_delay_ms=" << latest.tick.excess_delay_ms
              << " parse_us=" << latest.parse_us << "\n";
  }

  subscriber.CloseChannel();
  monitor.PrintSummary();
  return 0;
}
