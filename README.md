# claude-bwrap · WSL2 隔离版

从普通 WSL 终端运行 `claude-bwrap`，让官方 Claude Code 在私有 HOME 和独立网络命名空间中启动。隔离空间只有回环接口，Linux 子进程的外部连接经宿主中继和指定的 Mihomo 节点。这个分支只注册 `claude-bwrap`，可与日常版同时安装。[日常原生版](https://github.com/Embracecactus/wsl-agent-privacy/tree/main)

## 使用

1. 在 WSL2 准备修复版 bubblewrap、iproute2、系统 Python、PyYAML 和原生 Claude CLI。在可读取的当前 Mihomo 配置中准备一个固定节点的回环 HTTP 监听。已有日常版的专用监听可复用。
2. 从本分支安装 `claude-bwrap`，填写本机配置，启用独立 PATH 目录。[安装与撤销](claude-bwrap/references/setup.md) · [监听样例](claude-bwrap/network/mihomo.example.yaml)
3. 运行 `claude-bwrap --self-test` 核对代理 TLS、直接 IPv4、IPv6 和 DNS。再从业务项目运行 `claude-bwrap --version` 和 `claude-bwrap`。

WSL 宿主的系统代理和 TUN 可按其他应用的需要设置。隔离进程依赖自己的网络命名空间和中继；专用监听失联或启动预检失败时，会限制相应连接或启动。宿主的浏览器、Windows 程序和外部服务各有自己的访问路径。

| 用途 | 入口 |
| --- | --- |
| 固定路由、DNS、IPv6 与断线 | [网络配置与排障](claude-bwrap/references/network.md) · [复验](checks/README.md) |
| Windows 浏览器、USB 和可选工具 | [Windows 能力](claude-bwrap/references/windows.md) |
| 项目挂载、会话和升级 | [会话与权限](claude-bwrap/references/sessions.md) · [运行与更新](claude-bwrap/references/operations.md) |
| 查原版、版本演进及验证范围 | [隔离版开发日志](CHANGELOG.md) · [历史措施清单](PROTECTION.md) |

只需安装包时，可在仓库根目录执行 `python3 -I make_package.py claude-bwrap /tmp/claude-bwrap.zip`。安装包只包含本分支清单中的隔离版文件。
