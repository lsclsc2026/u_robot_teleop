cmake_minimum_required(VERSION 3.16)
project(a2_joystick_lab LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)
find_package(unitree_sdk2 REQUIRED)

add_library(joystick_protocol
    src/joystick_protocol.cpp
)
target_include_directories(joystick_protocol PUBLIC src)
target_compile_options(joystick_protocol PRIVATE -Wall -Wextra -Wpedantic)

add_library(network_packet
    src/network_packet.cpp
)
target_link_libraries(network_packet PUBLIC joystick_protocol)
target_include_directories(network_packet PUBLIC src)
target_compile_options(network_packet PRIVATE -Wall -Wextra -Wpedantic)

add_library(a2_button_mapper
    src/a2_button_mapper.cpp
)
target_include_directories(a2_button_mapper PUBLIC src)
target_compile_options(a2_button_mapper PRIVATE -Wall -Wextra -Wpedantic)

add_executable(a2_joystick_monitor
    src/main.cpp
)
target_link_libraries(a2_joystick_monitor PRIVATE joystick_protocol unitree_sdk2 Threads::Threads)
target_compile_options(a2_joystick_monitor PRIVATE -Wall -Wextra -Wpedantic)

add_executable(a2_network_bridge
    src/network_bridge.cpp
)
target_link_libraries(a2_network_bridge PRIVATE network_packet a2_button_mapper unitree_sdk2 Threads::Threads)
target_compile_options(a2_network_bridge PRIVATE -Wall -Wextra -Wpedantic)

add_executable(a2_motion_mode
    src/motion_mode.cpp
)
target_link_libraries(a2_motion_mode PRIVATE unitree_sdk2 Threads::Threads)
target_compile_options(a2_motion_mode PRIVATE -Wall -Wextra -Wpedantic)

enable_testing()
add_executable(protocol_tests tests/test_protocol.cpp)
target_link_libraries(protocol_tests PRIVATE joystick_protocol)
target_compile_options(protocol_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME protocol_tests COMMAND protocol_tests)

add_executable(network_packet_tests tests/test_network_packet.cpp)
target_link_libraries(network_packet_tests PRIVATE network_packet)
target_compile_options(network_packet_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME network_packet_tests COMMAND network_packet_tests)

add_executable(a2_button_mapper_tests tests/test_a2_button_mapper.cpp)
target_link_libraries(a2_button_mapper_tests PRIVATE a2_button_mapper)
target_compile_options(a2_button_mapper_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME a2_button_mapper_tests COMMAND a2_button_mapper_tests)
