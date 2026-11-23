---
name: claude-bwrap
description: 在 WSL2 中配置和核对 claude-bwrap 的独立网络空间、固定 Mihomo 监听、私有 HOME、时区及受控工具。
---

# Claude 的 WSL2 隔离入口

从普通 WSL 终端安装本 Skill，再通过 `claude-bwrap` 运行官方 CLI。安装步骤、自检及撤销见[安装与验收](references/setup.md)。

1. 确认用户实际调用的命令和工作目录。宿主侧可从本 Skill 运行 `/usr/bin/python3 -I scripts/audit.py host`。记录命令是在宿主还是隔离空间运行。
2. 在宿主用 `claude-bwrap --self-test` 核对固定出口、IPv4、IPv6 和 DNS。运行时需要关联具体连接的目标、源端口、入站与节点链。[网络排查](references/network.md)
3. 针对当前需求核对项目、可见账号、Windows 工具或更新。保留正在使用的项目、会话和已有的代理设置。[会话与权限](references/sessions.md) · [Windows 能力](references/windows.md) · [运行与更新](references/operations.md)
