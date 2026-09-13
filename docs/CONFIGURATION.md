# 配置与迁移差异

[返回首页](../README.md) · [安装](INSTALL.md) · [启动](USAGE.md)

## 网络与设备样例

| 项目 | 原部署样例 | 如何调整 |
|---|---|---|
| Unitree SSH | `unitree-a2-wifi` / `unitree` | WSL SSH config 与 `UNITREE_HOST` |
| Unitree WiFi | `172.18.21.114` | `UNITREE_WIFI_IP`；留空时从 SSH HostName 取值 |
| PC1 Windows LAN | `172.18.21.246` | BLE 使用 `PC1_WIFI_IP`，臂/视频使用 `PC1_IP`；显式 export 两者 |
| 下位机内网 | `eth0=192.168.123.162`、`net1=192.168.124.162` | 主视频源在 eth0 组播，狗控制接口按运动接收器配置 |
| BLE 手柄 | `00:00:00:07:FC:3A` | `BLE_ADDRESS` 或发送器 `--address` |
| 主臂 | 序列号 `5B3D047743`、示例 `/dev/ttyACM0` | `LEADER_PORT`，应核对实际设备 |
| 从臂 | 序列号 `5B3D047726` | 独立接收器 `--serial`；组合服务用代码中的默认值 |
| 腕部 | Microdia `0c45:64ab` | 宿主机自动检测 capture 节点 |
| 全景 | D435i `8086:0b3a` | `ARM_VIEW_MODE=uvc`，`ARM_VIEW_DEVICE` 指定 RGB 节点；识别为 D435i 后自动走 SDK |

历史文档或低层脚本出现的 `172.18.20.152`、`172.18.21.232` 等也是旧配置，不是统一的当前地址。IP、用户名目录、串口序列号与 BLE 地址保留是为了可追溯；它们不属于登录密钥。USB BUSID、ttyACM 编号、摄像头 by-path 会随接口和系统变化。

| 方向 | 端口／协议 | 用途 |
|---|---|---|
| Windows → Unitree Docker host 网络 | UDP 39001 | A2 遥控 |
| Unitree → Windows | UDP 39002 | 遥控 ACK |
| WSL → Unitree 宿主机 | UDP 39101 | 主从臂指令；ACK 回发送套接字的源端口 |
| Unitree → PC1 WSL | UDP 17200 | 主视频 RTP/H.264 |
| Unitree → PC1 WSL | UDP 17201 / PT96 | 腕部视频 |
| Unitree → PC1 WSL | UDP 17202 / PT97 | 全景视频 |
| PC1 → Unitree | TCP 22 | SSH 部署、生命周期与心跳 |
| A2 → Unitree eth0 | `230.1.1.1:1720` | 原主视频组播源 |

## 真正支持的入口变量

| 参数 | 入口与含义 |
|---|---|
| `DURATION_SEC` | 两个总入口运行秒数，默认 3600；必须为正整数，0 不是无限模式 |
| `ARM_REAL_CONTROL=YES` | 启用真实从臂，还需入口传 `--enable-arm`／接收器 `--enable-motors` |
| `A2_REAL_CONTROL=YES` | BLE 组合入口的狗控制确认；不是单独发送器的通用开关 |
| `WINDOWS_PYTHON` | BLE 组合入口可执行的 WSL 路径，如 `/mnt/c/.../python.exe` |
| `WINDOWS_BLE_SCRIPT` | Windows 路径，如 `D:\unitree_ble_test\ble_udp_sender.py` |
| `WINDOWS_CSV` | Windows CSV 路径；默认落在 D 盘上述目录 |
| `BLE_SEND_HZ` | BLE 组合发送频率，默认 50 |
| `DOCKER_TELEOP_ENTRY` | BLE 组合入口调用的本地 Python 入口，默认同目录 `pc1_ble_docker.py` |
| `REMOTE_DOCKER_TELEOP_ENTRY` | 仅本地 Python 入口缺失时用于 scp 获取，不是远端 run_teleop_docker.sh 路径覆盖 |
| `TELEOP_READY_TIMEOUT_SEC` | BLE 组合入口等待 READY 秒数，默认 30；内层 Python 另有自己的等待时间 |
| `ARM_VIEW_MODE`、`ARM_VIEW_DEVICE` | 全景模式和设备；默认 uvc，指定 D435 RGB 设备可避免误选 |
| `WRIST_JITTER_MS`、`ARM_VIEW_JITTER_MS` | 臂/视频启动器接收缓冲，默认各 12 ms |
| `USBIPD_EXE`、`WSL_EXE` | 主臂自动附加及权限处理时使用的 Windows 程序路径 |

`launch_pc1_operation.sh` 的命令行参数还包括 `--duration`、`--fps`、`--enable-arm`、`--no-video`、`--max-relative-target`、`--startup-max-delta`、`--startup-sync-speed`、`--startup-sync-tolerance`、`--wrist-fps`、`--wrist-bitrate-kbps`、`--wrist-jitter-ms`、`--arm-view-width/height/fps/bitrate-kbps/jitter-ms`，以及 Insta360 相关的 `--insta-yaw/pitch/fov`。实际参数名以[脚本 usage 与 case 分支](../remote_teleop/launch_pc1_operation.sh)为准。原配手柄总入口支持把附加 CLI 参数传下去；BLE 总入口没有通用的 `"$@"` 转发。

## 没有提供环境变量覆盖的路径

主臂总入口直接赋值 `LEROBOT_PY="$HOME/robot_ws/lerobot/.venv/bin/python"` 和 `LEADER_CAL="$HOME/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json"`。采用兼容目录或软链接，或在独立 `pc1_leader_sender.py` 中使用 `--serial`／`--calibration` 并自行选择解释器；仅 export 同名变量无效。

宿主机服务固定工作目录为 `$HOME/arm_remote`，真实从臂解释器为该目录 `.venv/bin/python`，`PYTHONPATH` 指向 `lerobot_src`。独立 `unitree_follower_receiver.py` 支持 `--serial`／`--calibration`，但组合入口没有透传它们。`WRIST_DEVICE` 是宿主机服务变量，不能假定在 PC1 export 后 SSH 就会自动传过去。调整低层默认时应在 PC1 部署源文件中做相应变更，因为下一次启动会 scp 覆盖宿主机脚本。

## unitree-review 与 unitree-dev

关联导航发布的默认容器名为 **`unitree-review`**。这里归档的历史遥操入口默认仍是 **`unitree-dev`**，本次整理保持原有业务行为。容器名只是运行目标，必须先确认该容器已按 `u_robot_move` 部署运动接收器。

单独启动 Docker 接收器时可明确指定：

```bash
python3 remote_teleop/pc1_ble_docker.py \
  --robot "$UNITREE_HOST" --pc1-ip "$PC1_WIFI_IP" \
  --container unitree-review --real-control
```

该命令会请求真实狗运动接收；使用前应停止冲突控制源，具体分步流程见[使用说明](USAGE.md)。仅想查看 SSH 命令可加 `--print-command`，它不发起 SSH。

`start_stack_ble_pc_remote.sh` 没有容器 CLI／环境变量透传，直接运行它仍选择历史 `unitree-dev`。新 `unitree-review` 部署采用上述独立接收器 + 独立 Windows BLE + 臂视频入口的分步方式；不要误以为设置 `CONTAINER=unitree-review` 已改变目标。若未来需要一键新容器入口，应另做有意识的实现变更，本次只发布现有代码。

真实导航和遥控共享运动锁；持锁冲突意味着另一控制任务尚未退出，应停止对应任务，不要删除锁文件抢占。
