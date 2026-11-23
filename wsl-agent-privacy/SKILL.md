---
name: wsl-agent-privacy
description: 审计、配置和验证 WSL2 中 Claude Code 与 OpenAI Codex 的固定代理、断线防直连和工具数据隐私。适用于 Clash/Mihomo、WSL 调用 Windows、专用 Chrome、会话交叉读取、CLI 更新或代理故障排查。
---

# WSL2 中的 Claude 与 Codex 隐私防护

在普通 WSL 终端进入仓库或分发包中的 wsl-agent-privacy 目录，运行 python3 -I install.py --target both。随后按[安装与验收](references/setup.md)选择只读审计或启用实际网络保护。

从用户实际调用的入口开始。先分清目标是隐藏本地公网 IP、保护工具返回的内容，还是诊断超时。三者需要不同证据。安装 Skill 后可在 Claude 输入 `/wsl-agent-privacy`，在 Codex 输入 `$wsl-agent-privacy`。Skill 自身不会接管流量。

## 开始工作

1. 从本 Skill 目录运行 `/usr/bin/python3 -I scripts/audit.py host`。请用户在实际使用的交互终端运行 `type -t claude; type -t codex` 区分函数和文件。核实 WSL 版本、启动器、原生程序和代理监听。报告中注明观察处于宿主还是已隔离的会话。现有保护先自检，保留有效入口、登录、历史及业务项目。
2. 日常 Claude 使用原生入口 `claude-local`，需要命名空间隔离时使用 `claude-bwrap`。普通名称 `claude` 可在两者之间切换。原生启动前验证固定节点，隔离模式另验证运行中的中继与断线阻断。安装、切换和撤销见[安装与验收](references/setup.md)。
3. 按下面的入口处理用户实际遇到的事。网络检查只验证明确的作用层。复核控制器连接时只输出匹配结果，日志检查默认只输出类别和计数。

| 场景 | 读取与操作 |
| --- | --- |
| Clash 模式、国内网站或游戏、TUN、DNS、IPv6、QNX、VPS 维护、SSH、Magpie | [网络分层排查](references/network.md) |
| 专用 Chrome 和普通 Chrome 隔离、网页语言、时区字体测试、Windows 软件、WSLg、USB ADB | [浏览器与 Windows](references/windows.md) |
| 会话无记录、双方互读历史、GitHub/OAuth/MCP、命令输出或媒体元数据、权限告警与审批 | [会话与权限](references/sessions.md) |
| 运行中连接、长时间监控、API 重试、额度恢复、更新实际未生效、剪贴板或 daemon | [监控与故障](references/operations.md) |

需要复盘整套防护及其来由时，可按[全流程主题对照](references/topics.md)逐项核对。

## 验收与交付

- 记录实际入口、专用监听与节点链。原生模式可核对客户端和宿主的工作目录、HOME 与命名空间。隔离模式另核对独立命名空间的 IPv4/IPv6 路由和模拟失联结果。只有客户端进程和代理连接能够关联时，才将连接归属于某一会话。
- 需要日常 Windows 业务时，逐项记录必要的程序、动作、数据和可能的出站位置。任何新增宿主通道都应有独立的验收结果。代理对文档内容、工具 stdout、插件和第三方连接器返回的数据没有自动清洗能力。
- 工具重启或升级后，从同一命令重新验证版本和路由。可从报告区分已实测、仅配置、未观察。无需为了诊断模仿第三方指纹分数；服务商账号判定只接受服务商给出的信息作为证据。
