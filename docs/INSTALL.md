# 安装与环境恢复

[返回首页](../README.md) · [配置参数](CONFIGURATION.md) · [启动](USAGE.md)

以下命令是迁移操作说明；本次整理未在机器上执行安装、构建或控制。源码不包含可直接克隆的 Windows／WSL 虚拟环境。采用原机兼容环境或按下述依赖分别恢复；不要把任一端的 Python 环境当作三端共用环境。

## 1. 获取源码与目录布局

将此仓库放在 PC1 WSL 的工作目录，记录其绝对路径：

```bash
cd ~/u_robot_teleop  # 按实际 clone 目录修改
export TELEOP_REPO="$PWD"
```

`remote_teleop` 入口按脚本自身位置查找相邻文件，可以整体放在新目录；但主臂解释器固定为 `$HOME/robot_ws/lerobot/.venv/bin/python`，主臂标定固定为 `$HOME/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json`。不能用 `export LEROBOT_PY=...` 覆盖它。旧目录存在时先保留原环境，选择复用兼容的实际路径或有意识地修改部署副本中的路径。

新 PC1 没有旧目录时，可用软链接保持原入口兼容：

```bash
mkdir -p "$HOME/robot_ws"
ln -s "$TELEOP_REPO/lerobot" "$HOME/robot_ws/lerobot"
```

这不是把 LeRobot 换成在线最新版：本仓库保留的 `motors_bus.py`、`so_follower.py` 含原机修改，安装时使用这里的源码。

## 2. Windows：BLE 与 USBIP

Windows 安装自己的 Python（原部署为 Python 3.10），使用该解释器安装 `bleak`。将 `windows_ble_test` 中全部 Python 文件复制到 Windows 可见目录，例如 `D:\unitree_ble_test`；发送器旁边的 `ble_command_mapper.py` 也要保留。WSL 路径下可复制：

```bash
mkdir -p /mnt/d/unitree_ble_test
cp "$TELEOP_REPO"/windows_ble_test/*.py /mnt/d/unitree_ble_test/
```

PowerShell 示例，实际解释器可以是安装路径：

```powershell
py -3.10 -m pip install bleak
py -3.10 D:\unitree_ble_test\scan_ble.py
```

在当前 Windows 上安装 usbipd-win，用它把主臂 USB 串口转给 WSL。先查看本次 BUSID；首次 bind 一般在管理员 PowerShell 中执行，随后 attach：

```powershell
usbipd list
usbipd bind --busid <本次主臂BUSID>
usbipd attach --wsl --busid <本次主臂BUSID>
```

`<本次主臂BUSID>` 是要替换的占位符，历史 `7-1` 不是固定值。WSL 确认对应 `/dev/ttyACM*` 与读写权限，必要时处理 `cdc_acm` 驱动和 `dialout` 用户组。入口会尝试按 `1a86:55d3` 自动附加、寻找 ttyACM，并在特定 WSL 环境通过 Windows 的 `wsl.exe -u root` 修复串口组和权限；多台同型号设备时应显式指定 `LEADER_PORT`。

## 3. PC1 WSL：图像显示与主臂环境

窗口使用 **`/usr/bin/python3`** 的 OpenCV／NumPy，GStreamer 是外部解码进程，不要求 OpenCV 编译了 GStreamer 后端。WSLg／可用显示环境必须存在。Ubuntu 风格系统包示例：

```bash
sudo apt-get update
sudo apt-get install python3-opencv python3-numpy gstreamer1.0-tools \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

主臂使用单独的 LeRobot 虚拟环境。随包 `pyproject.toml` 明确要求 **Python >=3.12**，源码也使用 Python 3.12 的类型别名语法；不能因为 Windows BLE 用 3.10 就照搬到这里。下面采用 Python 3.12 完整源码安装（依赖较多，包含 PyTorch），Python 3.12 与其 venv 支持需先由所用系统提供：

```bash
python3.12 -m venv "$TELEOP_REPO/lerobot/.venv"
"$TELEOP_REPO/lerobot/.venv/bin/python" -m pip install -e "$TELEOP_REPO/lerobot[feetech]"
```

依赖约束以 [pyproject.toml](../lerobot/pyproject.toml) 为准；[uv.lock](../lerobot/uv.lock) 保留原项目解析记录。Windows、WSL 和下位机平台不同，这份归档未包含完整冻结环境，不能把安装示例视为已经在所有系统验证过的安装器。

## 4. SSH、局域网与标定

在 WSL 的 `~/.ssh/config` 中配置当前下位机地址和本机自己的私钥：

```sshconfig
Host unitree-a2-wifi
    HostName 172.18.21.114
    User unitree
    IdentityFile ~/.ssh/id_ed25519
```

上面是配置样例，仓库不提供私钥。启动器要求 BatchMode SSH，需事先完成登录配置。PC1 接收地址必须能从 Unitree 局域网到达；原系统采用 WSL 镜像网络，NAT 内部地址不能直接照搬为 Windows BLE 的 ACK 地址。按照 [端口表](CONFIGURATION.md)配置 Windows／Hyper-V／WSL 防火墙，保持网络边界，仅放行需要的对端和端口。

主臂和从臂必须使用**各自设备**的标定 JSON，且与电机 EEPROM 一致。备份来源详见 [calibration/README.md](../calibration/README.md)。在新机器上，从实际设备的已确认备份恢复到各自默认路径；本仓库的两个备份不应自动复制为其他设备的默认值。标定工具会操作电机配置，不能当作只读检查工具随手运行。

## 5. Unitree 宿主机：从臂和三路视频

机械臂／摄像头当前运行在宿主机 `~/arm_remote`。启动器只会 scp 七个控制／视频脚本，**不会创建远端目录，不会安装依赖，不会复制 LeRobot 或标定**。先单独准备目标目录和环境。

下面是新宿主机的完整源码恢复路径示例，需在实际部署时由 PC1 发起：

```bash
ssh "$UNITREE_HOST" 'mkdir -p ~/arm_remote/lerobot'
# 复制源码与声明；避免同步本地 .venv 或 .git。
scp "$TELEOP_REPO/lerobot/pyproject.toml" "$TELEOP_REPO/lerobot/README.md" \
  "$TELEOP_REPO/lerobot/LICENSE" "$TELEOP_REPO/lerobot/uv.lock" \
  "$UNITREE_HOST:~/arm_remote/lerobot/"
scp -r "$TELEOP_REPO/lerobot/src" "$UNITREE_HOST:~/arm_remote/lerobot/"
```

在 Unitree 宿主机的新目录中建立虚拟环境和启动器需要的模块路径：

```bash
python3.12 -m venv "$HOME/arm_remote/.venv"
"$HOME/arm_remote/.venv/bin/python" -m pip install -e "$HOME/arm_remote/lerobot[feetech]"
ln -s "$HOME/arm_remote/lerobot/src" "$HOME/arm_remote/lerobot_src"
```

若已存在历史精简 `lerobot_src` 和 `.venv`，保留原可用部署，先决定如何迁移；不要让上面软链接命令覆盖旧目录。原下位机曾用精简 motor-only 模块布局，归档保留了 `minimal_lerobot_utils_init.py` 作为来源记录，本安装示例使用完整源码，不把该文件自动覆盖进 LeRobot。

从臂串口默认是 `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00`。若硬件不同，独立接收器有 `--serial`、`--calibration` 参数；组合入口并没有对应透传参数，见[配置](CONFIGURATION.md)。

宿主机视频需要 GStreamer、FFmpeg、V4L2 工具和摄像头权限。Ubuntu 风格依赖示例：

```bash
sudo apt-get install ffmpeg v4l-utils python3-numpy python3-gi \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

D435i SDK 分支使用宿主机 **`/usr/bin/python3`**，它必须能够加载匹配当前平台、Python 和相机的 `pyrealsense2`，以及 `gi`／GStreamer、NumPy。不要只把 SDK 装进 `~/arm_remote/.venv`。归档不包含 RealSense SDK 安装包；应沿用匹配原部署的 SDK 或按对应系统安装。代码兼容 `from pyrealsense2 import pyrealsense2 as rs` 的模块布局，只启 RGB，不启深度。

## 6. Docker 运动接收器与可选 C++ 工程

狗接收器安装参照 [宇树四足机器人室内导航与多点巡逻](https://github.com/lsclsc2026/u_robot_move) 内的 `scripts/deploy_teleop_docker.sh`、`scripts/run_teleop_docker.sh` 与 `docs/teleop.md`。远端入口在本仓库中固定为 `/home/unitree/unitree_robot_development/u_robot_move/scripts/run_teleop_docker.sh`；另行克隆目录时需要保持兼容位置或调整部署副本。新导航发布默认容器 `unitree-review` 与本仓库历史默认 `unitree-dev` 的差异见[配置文档](CONFIGURATION.md)。

`a2_joystick_lab` 包含原始 C++17 源码，需要 CMake >=3.16、Threads 和可由 `find_package(unitree_sdk2 REQUIRED)` 找到的 SDK2。仓库没有 SDK 或二进制。若维护者以后需要构建，命令为：

```bash
cmake -S "$TELEOP_REPO/a2_joystick_lab" -B "$TELEOP_REPO/a2_joystick_lab/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$TELEOP_REPO/a2_joystick_lab/build" -j2
```

本次发布未执行上述构建；已有可用 Docker 接收器不需要为了阅读本仓库而重新编译。
