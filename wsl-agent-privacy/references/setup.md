# 安装与验收

## 把 Skill 交给使用者

解压后进入含有本 Skill 的目录。在普通 WSL 终端执行下列命令。只需要其中一端时将 both 换为 claude 或 codex。

~~~bash
python3 -I install.py --target both
cd ~/.agents/skills/wsl-agent-privacy
/usr/bin/python3 -I scripts/audit.py host
~~~

仅装 Claude 时，最后两步使用 ~/.claude/skills/wsl-agent-privacy。新会话中可用 Claude 的 /wsl-agent-privacy 或 Codex 的 $wsl-agent-privacy。安装器只放置 Skill。已有可用防护时，从已有入口验证即可，无需叠加另一套代理。两个端的发现位置见 [Claude Skills](https://code.claude.com/docs/en/skills) 和 [Codex Skills](https://developers.openai.com/codex/skills/)。

若已安装 11 月 18 日的分发 Skill，先从保留的旧版目录运行 `python3 -I install.py --target claude --remove`，再从新版目录安装。旧版安装器只移除逐文件匹配的程序目录。配置、会话和项目保存在各自的位置。若提示本地文件有修改，保留该副本，先核对修改。

## 在新机器启用启动入口

原生模式使用系统 Python、Mihomo 和官方原生 CLI，可以直接使用当前项目、主目录和本机工具。下面的 bubblewrap、网络命名空间和 GPG 条件适用于隔离模式及经隔离入口执行的手动更新。

适用环境是 WSL2 的 Ubuntu/Debian、Python 3.10 以上、修复后的非 setuid bubblewrap（上游 0.12.0 及以上）、iproute2、系统 Python 的 PyYAML、CA 证书，以及原生 Linux ELF 版 Claude Code 或 Codex。Claude 原生升级还使用 gpg、gpgv。先用 command -v 和各自的版本命令核实。网络命名空间和当前内核的终端隔离检查必须可用。读取生成的 YAML 配置依赖 PyYAML（Debian/Ubuntu 包名 python3-yaml）。依赖由目标机器的系统包管理器和厂商提供，分发包内没有代理客户端或 CLI 二进制。

**1. 准备专用监听。** 在已有 Mihomo 配置的持久覆写处合并两个监听，节点填本机已有的具体出站代理名。保留现有 listeners 和规则。不要用订阅 URL、节点密码或会自动回落的策略组作为节点名。下面是示例端口，先检查冲突。变更只涉及两个本地监听。在对不熟悉的网络做首次外部探测之前，先在本机核对已经生效的监听和它的固定出站，因为探测本身也会向目标建立 TLS 连接。[Mihomo listeners](https://wiki.metacubex.one/en/config/inbound/listeners/)

~~~yaml
listeners:
  - name: claude-private
    type: http
    listen: 127.0.0.1
    port: 17897
    proxy: "YOUR_FIXED_NODE"
  - name: codex-private
    type: http
    listen: 127.0.0.1
    port: 17898
    proxy: "YOUR_FIXED_NODE"
~~~

Windows Clash 的这个监听必须能从 WSL 通过 127.0.0.1 到达。镜像网络和 WSL 内运行的 Mihomo 均可满足；传统 NAT 下需先解决本机 loopback 转接。不要为通过检测而把监听暴露给局域网。控制器用于只读查询固定节点和连接，可选现有 Windows 命名管道、WSL 的 Unix socket，或带 secret 的 loopback HTTP 控制器。[WSL 网络模式](https://learn.microsoft.com/en-us/windows/wsl/networking) · [Mihomo 控制器](https://wiki.metacubex.one/en/api/)

**2. 生成本机配置。** 从已安装的 Skill 目录运行以下命令。配置仅限本机所有者读取。把 rendered_profile 填为当前核心实际加载的生成配置在 WSL 可读的绝对路径。它含本地节点资料，只在内存中核对，勿提交到仓库。已有配置会保留。

~~~bash
/usr/bin/python3 -I scripts/guard.py init
~~~

在本地编辑 ~/.config/wsl-agent-privacy/config.json。ports 和 nodes 分别由 claude、codex 两项组成。executables 指向真正的原生入口，Claude 手动更新使用官方 ~/.local/bin/claude。Windows 的管道名应使用本机实际值。下面三种 controller 形式任选一行，HTTP 的 secret_file 必须是本机已有的、权限 0600 的普通文件，内容仅为 secret 一行，用实际绝对路径。无需把凭据粘贴到聊天。

~~~json
{"windows_pipe":"verge-mihomo"}
{"unix_socket":"/run/user/1000/mihomo/controller.sock"}
{"http_port":9090,"secret_file":"/absolute/private/controller-token"}
~~~

当控制器提供入站名时，可增加 inbounds，分别填 claude-private 和 codex-private，期望字段缺失或不符会拒绝。timezone、locale 只作用于专用进程，初始值为 Etc/UTC 和 C.UTF-8。选择本地已安装且符合业务实际的值即可。默认关闭 Wayland 与 USB。

**3. 选择日常模式。** 在 Skill 目录运行以下命令。第一条核对 Claude 的固定出口，第二条输出用于当前 shell 的 PATH 设置。首次安装默认选择原生。已有入口无参数重跑 `entries` 会保留上次选择。显式使用 `--claude-native` 或 `--claude-bwrap` 可来回切换。同一目录中的 `claude-local` 和 `claude-bwrap` 始终按各自的模式启动。

~~~bash
/usr/bin/python3 -I scripts/guard.py check claude
/usr/bin/python3 -I scripts/guard.py entries --claude-native
~~~

原生模式的预检是一次匿名 TLS 握手。启动后向进程提供专用代理变量，用户设置、工具及 Windows 程序仍能自行决定如何联网。可用 `claude-local --guard-check` 复核代理，用 `claude-local --version` 验证官方程序。

**4. 验收隔离入口。** 按实际安装的 CLI 分别执行。在这个模式下每条新的中继连接都需要最近 15 秒内的成功凭证，过期时先复核。

~~~bash
/usr/bin/python3 -I scripts/guard.py run claude --self-test
/usr/bin/python3 -I scripts/guard.py run codex --self-test
~~~

在希望启用的 WSL 终端执行第三步输出的 export 行，再运行 hash -r、type -t claude 和 type -t codex，并检查 type -P 的路径。已有同名函数或别名会优先于 PATH。首次验收也可直接执行下列命令。

~~~bash
~/.local/share/wsl-agent-privacy/bin/claude --version
~/.local/share/wsl-agent-privacy/bin/claude-bwrap --self-test
~/.local/share/wsl-agent-privacy/bin/codex --version
~~~

自检应看到 IPv4 和 IPv6 无直连路由、直接 UDP DNS 无路由、代理 TLS 成功、临时关闭的监听拒绝连接。现场验证中途失联应使用副本和独立测试监听；保留正在使用的 Clash/VPS。指定节点在代理核心本身的路由依赖实际生效的配置，成功的探测只给当时的链路提供证据。

## 数据、升级和撤销

- 原生模式沿用本机原有 HOME、历史和账号设置。分发版的隔离模式使用各自持久的私有 HOME，位于 ~/.local/state/wsl-agent-privacy/ 下的 claude 或 codex 目录。首次使用隔离模式可能需要登录。相同业务项目以原路径可写，Skill 会只读映射给相应 CLI。
- 默认共享当前 Linux 家目录下的业务项目。其他磁盘可在 project_roots 列出具体项目的绝对路径。不要选择整个用户目录、整块 Windows 盘、包含控制器或启动器的目录、带宿主控制套接字的项目，或会自动执行不受信任产物的宿主工作流。沙盒外消费共享文件的进程有自己的权限和出口。在家目录启动时进入专用 HOME。
- WSLg 需要时显式设置 wayland 为 true，仅映射单个 Wayland socket。USB ADB 的窄接口、专用 Chrome 和其它 Windows 工具见 [Windows 能力](windows.md)。登录流程可把厂商显示的地址在自己的专用浏览器打开并按提示操作。OAuth URL 和用户码只留在本机。
- 以后照常输入 claude、codex。Claude 原生安装的 claude update 或 claude upgrade 使用临时入口，成功后再通过相同代理验证官方签名和文件 SHA-256，原子切换真实 Claude 链接。Codex 的官方 standalone 布局用 codex update，只有显式更新才获得对应包目录的写权限。包管理器安装和布局变化应使用对应的官方更新流程。两者都以重新从受保护入口运行 --version 为准。[Claude 安装与签名](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing) · [Codex CLI](https://developers.openai.com/codex/cli/reference/)
- 退出当前临时启用 PATH 的终端即可回到原入口；若保存过 export 行，从 shell 配置移除该行并新开终端。要移除 Skill，请从解压保留的同版目录运行 python3 -I install.py --target both --remove。该命令逐文件核对，仅移除完整匹配的 Skill。原有会话、工具和专用 HOME 单独保留。

上述在线文档核对日期为 2026-11-17。没有控制器、没有原生 CLI 或未能完成某端验收时，可单独使用离线审计功能，并如实记录缺失条件。

可选的并列安装路径是 /usr/local/libexec/wsl-agent-guard/bwrap。启动器核对二进制与上级目录的所有权、权限和上游版本。采用发行版回补但无法用上游版本号识别的包须由管理员先独立确认。[Bubblewrap 上游修复公告](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx)
