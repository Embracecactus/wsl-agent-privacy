# 网络分层排查

先把问题放在正确层级。代理环境变量、Mihomo 规则、TUN 接管、DNS、WSL 路由、VPS 出口和远端服务响应是独立层。一个层通过不能证明其它层。

## 只读快照

在宿主 WSL 记录 ip route、ip -6 route、ss -ltn、代理相关环境变量和启动器的 guard 检查结果。再从 Mihomo 控制器读取对应 TLS 探测连接，按本地源端口、目标主机和链路名称精确匹配。Mihomo 的连接 API 可提供运行中连接信息，监听器可绑定出站代理或代理组。[Mihomo API](https://wiki.metacubex.one/en/api/)、[监听器说明](https://wiki.metacubex.one/en/config/inbound/listeners/)。

只看到 HTTP_PROXY 证明应用有可用配置。只看到 Clash 图标、节点名称、系统“全局”状态或 198.18.0.0/15 fake-IP 地址，都不能证明某条 API 请求经过了指定节点。

## 固定出口与断线

给 `claude-bwrap` 配置绑定具体节点的本地监听。也使用可选 Codex 守卫时，为它单设监听。启动前用匿名 TLS CONNECT 到各自官方主机，再按该连接的源端口回查控制器链路。缺少唯一匹配、监听器不只绑定 loopback、节点不等于预期，均拒绝启动。

如果目标是防本地公网 IP 回退，环境变量不够。把 CLI 放入没有 IPv4 和 IPv6 默认路由的网络命名空间，只公开 loopback 到私有 Unix socket 的 relay。relay 再连接已验证的本地专用监听。测试应分别覆盖正常代理 HTTPS 成功、直连 IPv4/IPv6/DNS 失败、relay 或代理停止后请求失败且直连仍失败、恢复后的固定路由复验。

这能证明被该命名空间约束的进程没有网络直连回退。它不能证明 Windows、手机、已有 GUI 服务、其他 WSL 进程或容器也没有直连。Bubblewrap 的安全性取决于调用参数，[官方说明](https://github.com/containers/bubblewrap#sandbox-security)。

API 响应中的“will retry”通常表示该连接或远端可用性失败。保留其时间、错误类别、代理连通性和控制器连接快照。没有抓包或服务端记录时，不能把一次超时归因于特定节点、VPS 维护或账号限制。

## DNS、TUN 与 IPv6

TUN 或 fake-IP 只说明某类流量由 Mihomo 接管。对受保护域名明确设置规则和 DNS 策略，分别测试 A、AAAA 与真实 HTTPS。若只测 A 记录，IPv6 分支仍未知。

DNS ECS 是递归解析器可能向权威侧传递客户端子网的扩展。检查解析器和 ECS 配置能减少这类附加信息，但不能通过 DNS 推断用户的物理位置或服务商风控结论。[RFC 7871](https://www.rfc-editor.org/rfc/rfc7871)。

DNS 排查可使用公开权威的反射端点分别观察解析器、上游看到的地址和 CDN 边缘，但报告只保留国家或数据中心级别的必要结果。Cloudflare trace 和 DNS 查询反映请求路径或递归器，不等于真实物理住址。对时延做对照时，互联网拥塞、anycast 和缓存会显著影响结果，不能由最低毫秒数推导城市。发送 ECS 0.0.0.0/0 只能请求不携带客户端子网，需同时检查解析器是否覆盖应用主动附带的 ECS。

指定 @ns1.google.com 会把查询发往显式指定的服务器，因此该次响应不能证明系统默认递归器的路径。Cloudflare trace 是 HTTPS 测量；再查询地址归属数据库也已经使用了 IP 地理数据。对照测试应区分系统默认解析、代理服务端解析和应用自带 DoH。回环 DNS、本地 fake-IP 与 HTTP 代理端口分别说明不同环节。

如果 VPS 强制 IPv4 出口，纯 IPv6 目标失败是设计结果。不要为了让一次探测通过而临时改全局 IPv6、系统 DNS 或节点配置。VPS 维护时，固定出口校验会失败关闭，待服务恢复后从相同启动器重新验证。

WSL 和 Windows 网络互通方式取决于网络模式与版本，代理端口、路由和防火墙应从两侧分别观察。[Microsoft WSL 网络说明](https://learn.microsoft.com/windows/wsl/networking)。

## 分流、国内应用、SSH 与 Magpie

先用一个国内 HTTPS 样本和一个游戏或客户端实际登录样本验证业务。HTTP 200 只证明该请求连通，不能代表完整游戏、支付、更新或 UDP 业务。规则修改应只匹配所需的 AI 域名与监听器，避免按 Chrome、系统代理或可执行文件路径做全局阻断。

SSH 到 VPS 与 Claude/Codex API 是两条连接。IPv6 SSH 能用并不证明 IPv4 代理稳定，反之亦然。对 VPS 只做状态和服务读取时，确认 SSH 使用的地址族、主机指纹和远端服务状态，不输出私钥、真实 IP 或完整配置。

先核对帖子的 Magpie 指向哪个项目及版本。同名软件有不同用途。若指 usemagpie.ai 的模型网关，SSH 本地端口转发可以给本机提供到自有服务器的通道。网关看到的账号和请求内容、记录策略、出口以及代理失效行为需要分别核对。[Magpie 产品文档](https://usemagpie.ai/docs/start)

远端网关会处理模型请求内容，适用前需确认其凭据、日志和数据保存方式。SSH 隧道保护本机到服务器的传输，无法替代服务端信任评估。不要为“防风控”使用未获服务商确认的订阅凭据中转。

## Cage 与 bwrap

这里的 Cage 指 Lee-xeo/Claude-Cage。其本地虚拟机与远端 SSH 部署的信任边界不同；bwrap 使用 Linux 命名空间并共享宿主内核。按工作负载比较文件挂载、宿主桥接、升级路径与所需 Windows 工具。使用 bwrap 时，可写父目录、shell 启动引用及可见的 Unix socket 仍会影响边界。[Claude-Cage 仓库](https://github.com/Lee-xeo/Claude-Cage)

QNX、Docker、虚拟机和 Windows 子程序各自可能有单独的网络栈。先确认它们的进程、接口和实际出站，再决定是否需要同一代理或独立策略。
