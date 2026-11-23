# 措施清单、验收和边界

本页记录 2026-11-18 原分发版的措施和当时的命令名。现行隔离分支使用 `claude-bwrap`，安装以[当前说明](claude-bwrap/references/setup.md)为准。

本记录从首次 WSL2 排查覆盖到固定出口、工具隔离、专用浏览器、更新兼容和时区启动检查。分发版使用占位节点、独立 HOME 和中性时区 UTC，接收者在自己机器上选择项目、程序和端口。时间均用 UTC 或仅列日期。官方资料核对日期为 2026-11-18。

## WSL、代理与 DNS

| 已采用的方法 | 如何验证，以及它保护什么 |
| --- | --- |
| 独立监听和固定节点 | 普通 `claude` 和可选 `codex` 使用各自的回环 HTTP 端口。先读当前核心实际加载的生成配置，核对唯一监听、明确绑定的具体代理和 IP 字面量节点。再进行无凭据 TLS 探测，将本地源端口、目的主机、`inboundPort`、`specialProxy`、最终节点链对应起来。只看节点链可能误把普通分流当作专用入口。 |
| 启动和使用中失联 | 宿主预检失败会终止启动。客户端及其 Linux 子进程在只有 loopback 的网络命名空间，主机代理中继通过受限 Unix socket 提供服务。新中继连接最多复用最近 15 秒内的成功复核；已有连接随实际传输中断。关闭应用层代理或工具自行禁用代理时，命名空间仍无外部 IPv4/IPv6 路由。 |
| 解析与域名 | 验证直接 DNS 不通、HTTP 代理和 HTTPS CONNECT 都传递原始目的主机名。Claude 四个后缀单独走固定节点上的 DoH，覆盖 ECS 为 /0。Codex 可选六个后缀分别指定。复查持久 merge 与核心生成配置；再用受控解析器与故障对照核对行为。配置文件和控制 API 不能单独证明每次运行时解析。 |
| 共享服务域名 | 核心 API、登录、更新、插件、第三方遥测和网页资源可能不共用域名。进程入口约束也覆盖新域名。官方列出 `http-intake.logs.us5.datadoghq.com` 和 `browser-intake-us5-datadoghq.com` 两个可选接收主机，分发启动器对 Claude 请求关闭可选用量遥测和错误上报。整个共享域名后缀加入全局规则会改变其他应用的出口。 |
| Windows、国内应用与其他网络 | 固定监听与服务后缀局部合并，普通应用保留原有路由。Clash 图标颜色、TUN 开关、rule/global、系统代理、QNX 枚举的网卡属于不同层。针对受影响的应用分别核对；游戏重启恢复本身不能归因于分流。VPS 的 IPv6 SSH 管理与客户端代理数据链路分别检查。 |
| 故障定位 | 分开核对监听、CONNECT、TLS、服务状态、额度与账号通知。临时 TLS EOF 只在既有固定路径做有界重试。Unix peer 地址表示本地进程通信。SSH 修复只针对管理通道；Magpie 与 SSH 隧道是调研方案，未作为此部署的依赖。 |

[分流实现](claude-bwrap/scripts/route.py) · [DNS 样例](claude-bwrap/network/mihomo.example.yaml) · [本地核心对照实验](checks/check_mihomo_ingress.py) · [官方端点表](https://code.claude.com/docs/en/network-config) · [Mihomo DNS](https://wiki.metacubex.one/en/config/dns/)

早期兼容阶段还分别检查过大小写 HTTP/HTTPS/ALL_PROXY、NO_PROXY、WSL 向 Windows 子进程传递环境变量，以及 TUN/strict-route 的系统级兜底。工具可以忽略代理变量，最终采用命名空间与受控 broker 作为两端普通入口的强制边界。QNX 的用户态虚拟网络与该入口分别验收。

现场也曾为共用默认解析器限制 ECS，经本地正反顺序对照后移除一个与该选项组合出现超时的解析端点。这项变更影响同用 Clash DNS 的普通应用，分发模板只包含服务专用后缀。更新使用 `downloads.claude.ai`；网页资源、连接器、Artifact、可选遥测与旧版 SDK 中出现过的域名分别归因。配置第三方后缀前需确定流量发起方。[Claude 官方网络清单](https://code.claude.com/docs/en/network-config)

## 系统时区、浏览器与工具内容

| 已采用的方法 | 如何验证，以及它保护什么 |
| --- | --- |
| 独立时区与语言 | 生成会话自己的 /etc、localtime、timezone 和 locale。两端每次启动都在会话内核对环境和系统文件，比较冬季、夏季的实际本地时间换算，错误仅显示通用原因。只修改一次 shell 的 TZ 不能覆盖忽略该变量的子进程。 |
| 专用 Windows Chrome | 单独 profile 和桌面启动脚本，WSL 先核对专用出口。浏览器用本地调试管道设置专用时区和语言，控制器在页面导航前核对。限制 QUIC、非代理 WebRTC UDP、非本地浏览器 DNS，并默认拒绝网页地理位置权限。测试页面、跨源 iframe、worker 的 Intl 和 Date，关闭代理后由本地测试源点核对是否收到直连。普通 Chrome 使用自己的 profile。 |
| 最小文件与进程权限 | bwrap 隔离网络、PID、IPC、UTS，去掉 capabilities，校验 no-new-privileges，私有 /proc、/dev、/tmp 与系统身份视图。程序及辅助代码只读，业务目录按需可写。现场版还对已有登录、同账户历史、启动器、本机 hook 和守护程序 socket 分别授权。分发版默认使用各自的持久 HOME，新机需重新登录。 |
| 跨工具会话和 GitHub | 现场实现允许显式选择单份兄弟工具的 JSONL 并只读挂载；适合传递完整上下文时使用。只需业务结论时优先选取本地摘录。共享工作树、Git 的提交时区和主动授权的会话内容都可能被工具读到。宿主 GitHub 凭据另行授权，Git SSH、HTTPS、浏览器 OAuth 和云端 MCP 分别核对权限与发起方。 |
| 原始 Windows 程序及手机 | 默认关闭通用 Windows 互操作。按需放行一个 Wayland socket。现场登录浏览器 broker 校验目的主机；USB ADB broker 校验可信 SDK、以会话别名显示设备、限制动作与参数。原始 PowerShell、任意 ADB shell 和网络 ADB 不属于默认业务权限。手机自己联网、截图、剪贴板等分别受对应平台控制。 |
| 剪映、配音等业务 | 能读写工程文件、能启动应用、能连云端配音是三件事。不识别代理变量的 WebSocket 客户端可使用本地 CONNECT 适配器，保留 TLS 校验，保护环境中遇代理中断就报错。离线回声测试不代表真实服务的登录、额度或配音成功。 |
| 工具和附件里的时区 | 文档日程、Git 时间偏移、媒体标签、日志、截图或用户粘贴的文字，不受系统时区隔离自动改写。复核曾定位到读取项目文档返回时区文字。分发的会话检查器仅在本地统计已选文件的命中类别。未自动改写原始业务资料，也未将翻译设为前置条件。 |

[WSL 入口](claude-bwrap/scripts/guard.py) · [时区启动检查](claude-bwrap/scripts/sandbox_entry.py) · [Windows 与 USB](claude-bwrap/references/windows.md) · [现场文件授权参考](reference/private_home.py) · [登录浏览器授权参考](reference/browser_broker.py) · [配音适配器](integrations/wsl_tts_proxy.py)

## 更新、权限与临时观察

- 以普通入口复验原生版本。Claude 更新时临时授予版本目录写权限，校验官方签名与平台哈希，再原子切换入口。Codex 单独核对 standalone 版本和稳定路径。并发更新、模型切换、WSL apt 更新和 CLI 程序升级分别有不同的验证条件。[更新实现](claude-bwrap/scripts/engine.py) · [Claude 官方安装](https://code.claude.com/docs/en/setup)
- 使用根用户所有、非 setuid、不可由普通用户改写的已修复 bubblewrap。现场使用并列安装的 0.13.1，可审阅上游标签、签名与摘要核对脚本。仓库分发源码和构建方法。[依赖验证](checks/build-bubblewrap.sh) · [上游修复公告](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx)
- 启动前复核 shell 别名、旧 guard、真正的 ELF 和 `--version`。退出时回收中继、线程与临时 socket，保留会话及客户端退出码。会话列表按项目筛选，恢复时先核对原目录和账号 HOME。Bash 规则中的宽泛通配符应按业务收窄。跳过客户端审批会增加工具权限，外层网络边界仍须独立验收。[运行故障](claude-bwrap/references/operations.md) · [权限与会话](claude-bwrap/references/sessions.md)
- 临时检查只观察指定进程树，报告观测时段、可见范围和连接类别。本方案不安装后台监控服务。专用 Chrome、普通 Chrome、Windows 桌面客户端和 WSL CLI 生命周期独立；已退出的桌面 VM 不承担 WSL 网络隔离。[审计脚本](claude-bwrap/scripts/audit.py)
- 分享 Git 仓库时核对待推送的完整历史。作者和提交者的日期都带时区偏移，工作树脱敏不会改写既有提交。独立的新仓库可使用已审查的文件快照、GitHub noreply 邮箱与 UTC 提交日期，推送前验证两组元数据。

## 证据层级

1. **原部署验收。** 两端固定出口、私有 HOME 和网络、版本、Codex DNS 生成配置，以及真实 Windows 专用 Chrome 曾完成宿主验收。最近一次时区补丁另做 20 项本地回归，注入三种错误时客户端均未运行。冬夏偏移在 Linux Chromium 的页面、iframe、worker 实测通过。该次新补丁的 Windows 实机偏移检查与旧版宿主回执分别记录。
2. **分发版。** 运行步骤见[复验说明](checks/README.md)。配置须使用接收者自己的节点和路径。现场版选定既有账号目录的两段源代码以参考形式提供；它们不由 Skill 安装器自动挂载。便携版的网络验证、更新和临时 HOME 可单独运行。
3. **账号判断。** 限流、超时、HTTP 403、中文界面和网页指纹分数都无法单独证明账号已被停用。旧版客户端的社区报告观察到了时区相关的提示词变化，未建立与某次账号处罚的因果关系。实际使用地区与账户授权受服务条款约束。[社区原始报告](https://github.com/anthropics/claude-code/issues/67120) · [账号通知与申诉](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals) · [服务地区](https://www.anthropic.com/legal/supported-regions)
