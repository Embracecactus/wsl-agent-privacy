# 日常 Claude · WSL2 原生版

`main` 用于在本机项目里运行官方 Claude Code。输入 `claude`，启动器先用专用 HTTP 监听向 Anthropic 做匿名 TLS 握手，并在 Mihomo 中核对实际连接的入站和固定 VPS 节点。通过后使用当前 WSL 的 HOME、工作目录和工具。需要独立网络空间时使用单独维护的 [claude-bwrap 分支](https://github.com/Embracecactus/wsl-agent-privacy/tree/claude-bwrap)。

## 从这里开始

1. 在 Windows 的 Clash Verge Rev 选择固定节点，给当前订阅加上 Claude 专用监听。按使用场景选择 Rule、系统代理与 TUN。[Clash 配置与模式对照](claude-native/references/network.md) · [可复制的订阅扩展脚本](claude-native/network/clash-verge.js)
2. 在普通 WSL2 终端安装 `claude-native`，填写本机配置，启用 PATH，再从实际项目目录启动。[WSL2 安装、验收与撤销](claude-native/references/setup.md)

| 使用场景 | Clash 建议 | 可验证的范围 |
| --- | --- | --- |
| 只有 Claude 需要固定 VPS | Rule；TUN 可关；系统代理按其他 Windows 应用需要设置 | `claude --guard-check` 核对专用监听到固定节点的实际连接 |
| Windows 应用也要遵循系统代理 | Rule；系统代理开；TUN 按需 | 其他应用通过普通监听时按自己的规则分流 |
| 下载器、构建工具等忽略代理变量 | Rule；需要接管时开启 TUN 和自动路由，按需要启用四个服务后缀的规则及 DNS 策略 | 实际进入 TUN 且识别出目标的连接可命中规则；用该应用的连接核对 |

原生进程与宿主共用网络和系统时区文件。遵守代理变量的程序会使用专用端口。需要保证 Linux 子进程直接 IP 和 DNS 都受阻时，请选隔离分支。[隔离版安装](https://github.com/Embracecactus/wsl-agent-privacy/tree/claude-bwrap)

日常可用 `claude --guard-check` 显示检测结果，`claude --version` 检查官方程序。`claude-local` 是同一原生入口的别名。已有正常工作的宿主入口可以继续使用。[开发日志与历史版本](CHANGELOG.md) · [配置复验](checks/README.md)
