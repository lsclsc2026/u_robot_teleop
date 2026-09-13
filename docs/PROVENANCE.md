# 来源、归档范围与发布限制

[返回首页](../README.md) · [第三方声明](../THIRD_PARTY.md)

## 原始来源

本仓库从只读原目录 `/home/unitree/teleop_handoff/pc1_teleop_handoff_20260913` 复制整理，发布工作副本位于 `/home/unitree/github_publish/2026-09-13-addons/u_robot_teleop`。源交接目录没有被编辑、执行或初始化 Git。本次仅为私有 GitHub 仓库增加结构化中文文档、来源说明、忽略规则、演示封面和 Release 视频导航。

| 内容 | 原始来源记录 | 本次处理 |
|---|---|---|
| `remote_teleop/` | PC1 `/home/shuochen/feishu/a2pro/local_arm_test/remote_teleop` | 保留控制、视频、Insta360、标定与历史测试源码；历史文档前加版本提示 |
| `windows_ble_test/` | Windows `D:\unitree_ble_test` | 保留发送器、映射器、扫描／检查／监视脚本 |
| `a2_joystick_lab/` | PC1 `/home/shuochen/a2_joystick_lab` | 保留 C++ 协议、映射、网络桥接、构建定义、测试与实验记录 |
| `lerobot/` | PC1 `/home/shuochen/robot_ws/lerobot` | 保留随包全部实际源码、docs、README、pyproject、uv.lock、LICENSE；去掉遗留 egg-info 安装元数据 |
| `calibration/aloha_leader.json` | 原 PC1 主臂标定备份 | 原样保留，明确设备适用范围 |
| `remote_teleop/calibration_export/aloha_follower.json` | 在 PC1 导出的历史从臂备份 | 原样保留，不声称等于当前下位机 EEPROM／标定 |
| 演示媒体 | 用户提供的 `狗子摇操.mp4` | 原速压缩为 Release 资产、生成封面与媒体清单；原始录像未放入 Git |

逐文件来源与 SHA-256 见 [SOURCE_FILES.tsv](SOURCE_FILES.tsv)。该表记录复制源文件与发布文件的对应关系，以及因为增加文档提示产生的哈希变化；哈希用于发布来源记录，不表示功能验证。

## LeRobot 修改与依赖

源交接给出的上游基准提交为 `7de2e4c1efb27d7d678947349dba0d81b61205d0`；明确有本地修改的文件为：

- `lerobot/src/lerobot/motors/motors_bus.py`
- `lerobot/src/lerobot/robots/so_follower/so_follower.py`

原交接包没有 Git 历史或完整补丁，因此该列表是交接记录中的已知修改，不宣称涵盖全部上游差异。这次未拉取替换上游，也未更改这些文件的实现。`lerobot/pyproject.toml` 中版本为 0.6.1、要求 Python >=3.12；本地目录内容才是本归档恢复的依据，不能只按提交重新 clone 后假定相同。

LeRobot 原许可及其源码版权声明完整保留，总项目未新增开源许可证。C++ 工程依赖的 Unitree SDK、Docker 镜像和第三方二进制不在本仓库内。

## 历史文档优先级

本仓库根 README 与 `docs/` 下新写的架构、安装、配置、使用、视频和排障文档解释当前归档实现。以下材料保留历史状态与操作记录：

- [原始交接 README](history/HANDOFF_SOURCE_20260913.md)
- [原始 MANIFEST](history/ORIGINAL_MANIFEST.sha256)
- [remote_teleop 旧 README](../remote_teleop/README.md)、[旧双版本启动文档](../remote_teleop/START_TWO_CONTROL_VERSIONS.md)、[归档交接记录](../remote_teleop/HANDOFF_20260913.md)
- [a2_joystick_lab 早期说明](../a2_joystick_lab/README.md)及实验／Task 文档

旧说明中可能出现旧 IP、历史 `/home/shuochen` 路径、旧 compositor、Insta360、旧视频分辨率或“整个工程只读”的阶段性结论；这些只适用于原记录语境。旧 Task 或 LeRobot 上游文档也可能引用未随交接包提供的文件／图片，不代表本次发布漏掉了源包中的源码。

`ORIGINAL_MANIFEST.sha256` 保留了原交接包文件名和哈希，适用于原交接根目录；本次 README 已重写，部分历史文档添加提示，也移除了 egg-info，因此不要在新仓库根目录直接把它当作新发布的全仓校验表。

## 本次保留和排除

保留实际控制／视频实现、实验源码、历史测试、配置样例、设备标定备份、LeRobot 源码和许可。排除 `.git`、虚拟环境、缓存、egg-info、build/install、日志／CSV、原始录像、重复压缩包和凭据；Windows／WSL 驱动、电机 EEPROM 标定及 Docker 部署环境不能通过复制源码自动恢复。

标定适用范围见 [calibration/README.md](../calibration/README.md)。历史 IP、机器目录与设备地址属于配置样例，未为“脱敏”擅自改变默认实现。发布只做文件尺寸、敏感凭据与 Markdown 链接检查，没有运行控制程序、语法编译、测试套件、摄像头或机器人操作。源码中保留测试文件不表示测试已通过。

当前控制能力来自原使用与交接记录。最新视频实现尚缺三路同时实机 FPS 和端到端延迟验收，演示视频展示实际场景但不填补这个版本验收缺口。后续修改应在自身任务范围内明确建立运行证据。
