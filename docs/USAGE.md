# Windows / WSL / Unitree 使用流程

[返回首页](../README.md) · [安装](INSTALL.md) · [配置](CONFIGURATION.md)

本文是实际运行时的操作说明，本次发布未执行这些操作。先完成环境、标定、网络和容器部署，确保上一轮进程已正常结束。真实从臂退出默认卸扭矩，启动／退出时要托住从臂；原配手柄与 BLE 控制源不要同时启用，真实导航与遥控不要同时运行。

## 1. PC1 WSL 公共配置

在每个运行终端中设置本机实际值，路径和地址以下列历史样例说明：

```bash
cd ~/u_robot_teleop
export TELEOP_REPO="$PWD"
export UNITREE_HOST=unitree-a2-wifi
export UNITREE_WIFI_IP=172.18.21.114
export PC1_WIFI_IP=172.18.21.246
export PC1_IP="$PC1_WIFI_IP"
export LEADER_PORT=/dev/ttyACM0
export ARM_VIEW_MODE=uvc
export ARM_VIEW_DEVICE=/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4.1.1:1.3-video-index0
export DURATION_SEC=3600
```

BLE 版再设置 Windows 解释器与脚本路径。`WINDOWS_PYTHON` 是 WSL 能执行的路径，另外两个路径传给 Windows Python，采用 Windows 格式：

```bash
export WINDOWS_PYTHON='/mnt/c/Users/47487/AppData/Local/Programs/Python/Python310/python.exe'
export WINDOWS_BLE_SCRIPT='D:\unitree_ble_test\ble_udp_sender.py'
export WINDOWS_CSV='D:\unitree_ble_test\ble_session.csv'
export BLE_ADDRESS='00:00:00:07:FC:3A'
export BLE_SEND_HZ=50
```

Windows 用户目录与盘符通常需要修改；固定 `WINDOWS_CSV` 会复用同一路径，需要多次留档时每轮改名。USB 主臂仍由 WSL 访问，BLE 仍由 Windows 访问。

## 2. 原配手柄控狗 + 主从臂 + 三路视频

原配手柄直接控制 A2，本入口只管理机械臂／视频。关闭 PC BLE 发送器，不启动 UDP 狗接收器。在 PC1 WSL 执行：

```bash
cd "$TELEOP_REPO/remote_teleop"
ARM_REAL_CONTROL=YES ./start_stack_native_remote.sh
```

需要调整视频或同步参数时，这个总入口支持附加参数，例如 `--wrist-bitrate-kbps 700 --arm-view-bitrate-kbps 800`。不要把这种参数透传能力套用到 BLE 总入口。

## 3. BLE 手柄 + 主从臂 + 三路视频（历史 unitree-dev）

本组合入口仍使用 `pc1_ble_docker.py` 的默认容器 **unitree-dev**。只有该容器已部署对应接收器时使用本节；若使用新发布默认 **unitree-review**，改用下一节分步运行。

关闭原配 A2 手柄，在 PC1 WSL 执行：

```bash
cd "$TELEOP_REPO/remote_teleop"
ARM_REAL_CONTROL=YES A2_REAL_CONTROL=YES ./start_stack_ble_pc_remote.sh
```

顺序为：SSH 启动 Docker 接收器并保持心跳 → 等待 `TELEOP_READY` → 启动臂／视频 → 启动 Windows BLE。原实现向 Windows 发送器传 `--no-deadman`，因此不要求持续按 F1 才启用；这是保留的历史行为。两项 `*_REAL_CONTROL` 只表达对应入口的启用条件，不能替代现场控制源互斥。

## 4. 明确选择 unitree-review 的分步运行

先按关联 [宇树四足机器人室内导航与多点巡逻](https://github.com/lsclsc2026/u_robot_move) 完成目标容器的遥操接收器部署，并停止导航任务。以下终端各自保持运行；分步方式没有组合脚本自动统一回收所有终端的功能。

**终端 A，PC1 WSL：启动狗运动接收器。**

```bash
cd "$TELEOP_REPO"
python3 remote_teleop/pc1_ble_docker.py \
  --robot "$UNITREE_HOST" --pc1-ip "$PC1_WIFI_IP" \
  --container unitree-review --real-control
```

看到 `TELEOP_READY` 后再启动输入端。该 Python 入口用 SSH 向宿主机固定路径的 `run_teleop_docker.sh` 请求目标容器，心跳与会话需持续存在。

**终端 B，PC1 WSL：启动真实主从臂和视频。**

```bash
cd "$TELEOP_REPO/remote_teleop"
ARM_REAL_CONTROL=YES ./launch_pc1_operation.sh \
  --enable-arm --duration 3600 --fps 100 \
  --max-relative-target 8.0 --startup-max-delta 80 \
  --startup-sync-tolerance 2
```

这里显式沿用两个总入口使用的参数；底层 `launch_pc1_operation.sh` 独立默认启动姿态硬上限为 25，总入口传入 80，不能混为一个默认值。

**终端 C，PC1 WSL 调 Windows Python：启动 BLE。**

```bash
"$WINDOWS_PYTHON" "$WINDOWS_BLE_SCRIPT" \
  --address "$BLE_ADDRESS" --target "$UNITREE_WIFI_IP" \
  --duration 3600 --send-hz 50 --no-deadman --csv "$WINDOWS_CSV"
```

只需原配手柄时不要启动 A、C；只查看已有视频可使用下一节窗口入口。原实验的其它按钮映射／低层模式记录保存在 [a2_joystick_lab](../a2_joystick_lab/README.md)，应区分历史实验和本次默认链路。

## 5. 独立窗口、dry-run 与日志

仅在下位机视频已经发送到 PC1 时，以下命令打开接收窗口，不负责部署发送端：

```bash
cd "$TELEOP_REPO/remote_teleop"
./video_dashboard.sh
```

`launch_pc1_operation.sh` 不传 `--enable-arm` 时，从臂接收端 dry-run，不打开从臂串口；但仍会**部署远端脚本、真实采集视频、连接并配置主臂、发送主臂 UDP**，不能把它理解为纯离线检查：

```bash
cd "$TELEOP_REPO/remote_teleop"
./launch_pc1_operation.sh --duration 30
```

PC1 日志在 `remote_teleop/logs`，宿主机在 `~/arm_remote/logs`。可先列出新一轮文件，再按实际文件名读取：

```bash
ls -lt "$TELEOP_REPO/remote_teleop/logs"
tail -n 80 "$TELEOP_REPO/remote_teleop/logs/video_dashboard_本轮时间.log"
python3 "$TELEOP_REPO/remote_teleop/analyze_remote_arm_csv.py" \
  "$TELEOP_REPO/remote_teleop/logs/arm_sender_本轮时间.csv"
```

上面的“本轮时间”需要替换成实际文件名。`VIDEO_FPS` 是解码到达率；`REALSENSE_PUSH_FPS` 是 SDK 送编码器帧率，含义见[视频说明](VIDEO.md)。

## 6. 停止与回滚

组合入口运行时按一次 `Ctrl+C`，其清理逻辑会结束所管理的本地和远端进程。关闭视频窗口、按窗口 `q`／Esc 只结束窗口，控制可能继续。分步运行时，托住从臂，停止 Windows BLE 输入与终端 A 的接收会话，再停止终端 B 的臂视频服务；各终端需分别结束。按现场既有停止流程处理原配手柄控制。

`pc1_ble_docker.py` 退出时先关闭 SSH 控制通道，再回收自己启动的发送器；分步终端 C 不属于它的子进程，要单独结束。接收器／USB 异常不保证所有组件总能完成清理，剩余占用可根据[排障说明](TROUBLESHOOTING.md)定位。

回滚应停止本轮、保留实际目标目录备份、恢复 PC1 的部署源文件，再让入口同步到宿主机。只恢复下位机脚本可能在下次启动时又被 PC1 覆盖。历史备份压缩包不随仓库提供，也不应把历史标定当作代码回滚的一部分直接覆盖。
