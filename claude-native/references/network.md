# 在 Clash Verge Rev 配置日常 Claude

如果目标是让 WSL 里的 `claude` 走固定 VPS，同时少影响本机，选择 **规则模式（Rule）＋ Claude 专用监听**。只为这个命令使用代理时，TUN 和 Windows 系统代理都可以关。已有需要它们的应用，可以保留各自的开关。

## 一次配置固定节点

1. 打开 Clash Verge Rev 的「订阅」，找到正在使用的订阅，打开它的扩展脚本编辑器。复制本仓库的脚本，将 `claudeNode` 改成该订阅 `proxies` 中固定 VPS 的具体节点名。示例端口为 `17897`，若已占用，在脚本和 WSL 配置里一起换。启动器要求节点使用 IP 地址，且没有上游 `dialer-proxy`。[扩展脚本](../network/clash-verge.js) · [Verge 扩展脚本用法](https://www.clashverge.dev/guide/script.html)
2. 默认保留 `coverOtherClients = false`。脚本会增加一个 `127.0.0.1` 上的 HTTP 监听，把它的 `proxy` 直接设为所选节点。若已有自己的扩展脚本，把这段处理合并进原有的 `main(config)`，保留原脚本的其他处理。保存、应用订阅，在运行配置中核对 `listeners`、端口和出站名。已有同名或同端口的不同监听会报错。[Mihomo 监听器](https://wiki.metacubex.one/config/inbound/listeners/)
3. 若浏览器等其他客户端的 Claude 流量也要走该节点，可把 `coverOtherClients` 改为 `true`。脚本将四条域名后缀规则放在既有规则和 `MATCH` 之前，保留其他分流。它还为这四个后缀合并 Mihomo DNS 的 `nameserver-policy`。要使用这些 DNS 策略，请启用 Mihomo DNS，并让该客户端的查询实际交给它。四个后缀是 `anthropic.com`、`claude.ai`、`claude.com`、`claudeusercontent.com`。第三方 MCP、MCP 自己访问的站点及其他域名仍按各自规则处理。[Mihomo 路由规则](https://wiki.metacubex.one/config/rules/) · [DNS 配置](https://wiki.metacubex.one/config/dns/)
4. 在 WSL 配置同一个监听端口、具体节点名及核心实际加载的配置文件，然后运行 `claude --guard-check`。成功时能看到预检通过，普通 `claude` 启动成功时安静进入官方程序。[WSL 安装与验收](setup.md)

手工维护 Mihomo 配置时，可逐项合并 YAML 样例，保留原有的监听、规则、DNS 上游及兜底规则。Clash Verge Rev 从 v2.5.5 起对扩展配置里的 `dns` 和 `hosts` 使用整体覆盖，把样例中几行 DNS 直接当整段覆写会丢掉原有字段。上面的脚本只更新选中的策略。[YAML 样例](../network/mihomo.example.yaml) · [Verge 配置合并说明](https://www.clashverge.dev/guide/extend.html)

## Rule、Global 和 Direct 怎么选

| 核心模式 | Claude 经过专用监听 | 普通 HTTP / SOCKS 入口，或已进入 TUN 的流量 |
| --- | --- | --- |
| **Rule**（日常建议） | 走监听绑定的固定节点 | 按规则自上而下匹配。启用上述四条规则后，识别出的对应域名走固定节点，其他应用继续按原规则分流 |
| **Global**（全局） | 仍走监听绑定的固定节点 | 普通流量走 `GLOBAL` 当前选项。该组选了其他出口时，普通应用也跟着走 |
| **Direct**（直连） | 仍走监听绑定的固定节点 | 普通流量走直连，域名分流规则不再为普通应用选择固定节点 |

这里“专用监听”的前提是实际连接进入带 `listeners[].proxy` 的那个端口，且核心在运行。用 Mihomo v1.19.33 在独立网络空间实测了三种模式、专用与普通入口以及固定节点失联。`GLOBAL` 在实验中选为 `DIRECT`，两种入口走出了不同路径。[复验命令与边界](https://github.com/Embracecactus/wsl-agent-privacy/blob/main/checks/README.md) · [Mihomo 模式](https://wiki.metacubex.one/config/general/)

## Windows 系统代理和 TUN 怎么开

| 你的使用方式 | Windows 系统代理 | Clash TUN / 虚拟网卡 | 应如何验收 |
| --- | --- | --- | --- |
| 只想给 WSL 的 `claude` 固定出口 | 可关 | 可关 | WSL 运行 `claude --guard-check`。启动器显式设置代理，连接到专用监听 |
| 希望遵循系统代理的 Windows 浏览器和软件也分流 | 开 | 可关 | 用浏览器发一次请求，在 Clash「连接」查看普通入口、命中规则、代理链 |
| 还需要接管会忽略代理的应用或 UDP | 按其他软件需要 | 开，并启用自动路由（`auto-route`） | 用该应用做一次实际业务请求，核对连接的入站类型、目标和代理链；另测日常需要的局域网或 VPN |
| 已经同时使用系统代理和 TUN | 可保留开 | 可保留开 | 遵循系统代理的连接可能仍从普通代理端口进入，受路由捕获的连接从 TUN 进入；分别看具体连接 |

Windows 上在 Verge 的「设置」中切换系统代理、TUN / 虚拟网卡。启用 TUN 需要创建虚拟网卡的权限，可使用 Verge 的服务模式。`auto-route` 调整系统路由；搭配它启用 `strict-route` 时，Windows 还会限制多网卡 DNS 的外发路径。严格路由会影响其他应用、VPN 或局域网解析，按这些业务的实测结果决定是否开启。只想保留本地原生使用体验时，可以从表格第一行开始。[Verge 快速入门](https://www.clashverge.dev/guide/quickstart.html) · [Mihomo TUN 配置](https://wiki.metacubex.one/config/inbound/tun/)

2026-11-23 的一台实际主机使用 WSL 镜像网络、Rule、Windows 手动系统代理开启、TUN 开启、自动路由开启、严格路由开启。该记录来自配置与运行状态的只读检查。三种核心模式的切换验证在独立测试核心完成，未切换这台 Windows 主机的网络。

## 判断一次连接究竟走哪里

- **启动时**，guard 先读已生效的配置，检查专用监听绑定回环和具体 IP 节点，再经该监听向 `api.anthropic.com:443` 做匿名 TLS 握手。它按源端口和目标回查 Mihomo，要求入站端口、`specialProxy` 和单节点代理链都吻合。失败会停止本次启动。
- **运行中**，`claude` 与 WSL 宿主共享网络命名空间。遵守显式代理的子程序使用同一端口；自行开套接字的程序取决于宿主路由和实际 TUN 接管情况。应用自带 DoH、已打开的浏览器以及外部服务也应分别验收。需要在代理失联后继续阻断 Linux 子进程直连时，可使用隔离分支。[隔离版](https://github.com/Embracecactus/wsl-agent-privacy/tree/claude-bwrap)
- **排障时**，如果 `claude --guard-check` 失败，先核对 `type -a claude`、WSL 的回环可达性、生成配置路径及控制器，再查专用监听和固定节点。系统代理图标、TUN 开关、DNS fake-IP 和一次浏览器 IP 查询，各自只反映那一层的状态。[WSL 排查步骤](setup.md) · [Claude Code 官方代理说明](https://code.claude.com/docs/en/network-config)

上述文档链接核对日期为 2026-11-23。
