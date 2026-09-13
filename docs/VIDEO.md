# 三路视频与演示

[返回首页](../README.md)

[![主摄像头、Arm 与 Wrist 演示封面](media/overview.jpg)](https://github.com/lsclsc2026/u_robot_teleop/releases/tag/v0.1.0-review)

[Release：原速演示 teleop-demo-1x.mp4](https://github.com/lsclsc2026/u_robot_teleop/releases/tag/v0.1.0-review)。原演示约 55 秒，精确时长 54.534 秒，无音轨；发布版 H.264、1440×772、8,225,108 字节。处理仅缩放／压缩，没有加速或剪短；封面截自第 25 秒。文件信息与 SHA-256 见 [video-manifest.json](media/video-manifest.json)。原始录像不放入 Git，压缩演示作为 Release 资产提供。

演示呈现一个主画面和右侧 Arm／Wrist 两个画面。容器文件的 30 FPS 是录像编码帧率，画面内约 20 FPS 的叠字也不能单独证明三路传感器输出、最新源码版本的解码速度或端到端延迟。

## 当前源码的三路路径

| 画面 | 下位机采集／处理 | 网络输出目标 |
|---|---|---|
| Main | eth0 接收 `230.1.1.1:1720` 原始 RTP/H.264 组播，转发 | PC1 UDP 17200；分辨率／帧率／码率跟随原始流，没有转码降带宽 |
| Wrist | Microdia MJPEG 1280×720@30，videorate 降帧、缩放、x264 | 480×270@20，目标 700 kbps，UDP 17201／PT96 |
| Arm / D435i | RealSense SDK 只采 RGB 640×360@30，单帧队列、appsrc、x264 | 480×270@20，目标 800 kbps，UDP 17202／PT97 |

这些是默认配置目标，码率不是严格的 UDP 流量上限。全景入口仍名为 `unitree_uvc_camera_sender.sh`，检测选定节点为 D435i 后调用 `unitree_realsense_sender.py`；其它设备保留 UVC／FFmpeg 分支。Insta360 相关脚本是历史可选路径，默认全景使用 uvc 模式。

## PC1 显示与故障降级

`video_dashboard.sh` 直接调用 `dashboard_latest.py`，每路独立的 GStreamer 进程解码，通过独立线程读取原始 BGR，每路只保留最新帧。UI 默认按 20 FPS 读取三路快照，1280×480 窗口布局左侧 848×480、右侧上下各 432×240。BGR 行宽按对齐处理。

每 5 秒打印的 `VIDEO_FPS Main=... Arm=... Wrist=...` 是该路**解码到达率**。超过 0.75 秒无新帧时该区域黑屏并打印 `WARNING VIDEO_STALE`，恢复后打印 `VIDEO_OK`。解码器失败会重试；视频任务在独立进程组中运行，单路异常可降级，关键机械臂错误仍可能让组合服务退出。

D435i SDK 内部与 appsrc 均采用单帧队列，并允许丢弃过期帧。`REALSENSE_READY` 说明采集初始化完成；`REALSENSE_PUSH_FPS` 说明送入编码器的频率，不是 PC1 解码率。

## 历史问题与未完成事项

原记录包括残留进程占用摄像头、重复主视频转发、腕部缺少 30→20 FPS 的 videorate 导致 not-negotiated、D435 V4L2 零字节帧，以及旧 compositor 合成窗口约 10 FPS。当前源码针对这些现象改用了独立解码与 SDK 路径。

当时的约 2 Mbps 接收量和 socket 零积压／零丢包，不能完全排除 WiFi 抖动、空口丢包或编码前掉帧；旧窗口 10 FPS 也不能证明 compositor 是唯一原因。最新三路同时实机运行的实际帧率和玻璃到玻璃延迟尚未完成验收。本次发布没有追加运行验证，旧测试也未据此宣称通过。
