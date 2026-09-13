# 第三方源码与依赖

本次发布没有为整个 `u_robot_teleop` 项目新增 MIT、Apache 等总项目许可证。私有仓库可见性也不等同于重新许可。自行编写的整合脚本、文档和实验代码未附总项目开源授权；第三方文件保留原来的版权声明和许可。

| 组件 | 本仓库内容与来源 | 许可／处理方式 |
|---|---|---|
| LeRobot | [lerobot/](lerobot/)，来自原 PC1 修改过的源码副本；上游项目由随包 `pyproject.toml` 指向 Hugging Face LeRobot | 保留 [Apache-2.0 原文](lerobot/LICENSE)、源码头部声明、README、pyproject 与 uv.lock；其中夹带组件按各文件自身声明处理 |
| 本地 LeRobot 修改 | `lerobot/src/lerobot/motors/motors_bus.py`、`lerobot/src/lerobot/robots/so_follower/so_follower.py`，原交接明确记录这两个文件有本地修改 | 此处明确标记为经过本地修改的分发副本，不能当作未改动上游版本；本次发布未改这些文件 |
| Unitree SDK2 | C++ 源码通过 `find_package(unitree_sdk2 REQUIRED)` 链接；协议布局来源见原实验文档 | SDK 的头文件／库／构建产物未包含。部署者单独取得 SDK 并遵守其许可 |
| Bleak、Feetech SDK、OpenCV、NumPy、GStreamer、FFmpeg、RealSense SDK | 外部运行依赖；部分由 LeRobot 的依赖声明约束 | 安装时取得各自软件和许可，本仓库不打包其二进制 |
| 第三方文档图片／徽章 | LeRobot 原 README 与文档中的原始链接 | 保留来源引用；远程素材不表示本项目拥有其版权 |

LeRobot 基准提交由交接记录给出：`7de2e4c1efb27d7d678947349dba0d81b61205d0`。源交接包没有 `.git` 和补丁历史，无法仅凭归档确认完整上游差异；保留整个现有源码，未用在线版本覆盖。来源清单与发布整理说明见 [docs/PROVENANCE.md](docs/PROVENANCE.md)。
