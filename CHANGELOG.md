# claude-bwrap 开发日志

| 日期 | 变更 | 可追溯记录 |
| --- | --- | --- |
| 2026-11-16 至 11-17 | 开始在 WSL 使用独立网络空间与宿主代理中继，逐项核对直连、DNS 和进程清理。 | [完整项目时间线](https://github.com/Embracecactus/wsl-agent-privacy/blob/main/CHANGELOG.md) |
| 2026-11-18 | 首个可检出的隔离分发版，包含私有 HOME、固定监听复核、时区检查和受管 CLI 更新。 | [原始提交 fa3f00a](https://github.com/Embracecactus/wsl-agent-privacy/commit/fa3f00a216e390dc9b6f068d979590875b72f3af) · [当时的验收](PROTECTION.md) |
| 2026-11-23 | 从以上隔离分发快照建立长期分支。Skill、安装包及 PATH 目录改名为 `claude-bwrap`。它只注册同名命令，继续复用原隔离版配置与私有 HOME。 | [安装与共存](claude-bwrap/references/setup.md) · [复验](checks/README.md) |

两个分支可独立更新。历史标签 `claude-bwrap-2026-11-18` 固定原始隔离分发提交，`claude-native-2026-11-23` 固定拆分前的双入口快照。[历史标签](https://github.com/Embracecactus/wsl-agent-privacy/tags)
