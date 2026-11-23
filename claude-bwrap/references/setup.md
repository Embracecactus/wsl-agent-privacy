# 在 WSL2 安装和验收 claude-bwrap

## 准备

在普通 WSL2 终端准备官方 Linux ELF 版 Claude Code、系统 Python 3.10+、PyYAML（Debian/Ubuntu 为 `python3-yaml`）、CA 证书、iproute2，以及支持用户和网络命名空间的修复版非 setuid bubblewrap。启动器要求上游 0.12.0 或更新版本，并检查二进制及父目录权限。也支持 `/usr/local/libexec/wsl-agent-guard/bwrap`。Claude 的受管更新还使用 `gpg` 和 `gpgv`。[Bubblewrap 修复公告](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx) · [Claude 官方安装](https://code.claude.com/docs/en/setup)

准备能从 WSL 通过 `127.0.0.1` 到达的 Mihomo HTTP 监听。Windows Clash 搭配 WSL 镜像网络，或同一 WSL 内运行 Mihomo，均可使用。若有可用的 Claude 专用监听，沿用同一个端口和节点；首次部署时把下面的条目合并到当前订阅的 `listeners`，并将占位符换成自己的具体出站节点。启动器要求节点服务器为 IP 地址，并直接连接该节点。对 Linux 隔离的验收不需要切换 Windows 的系统代理、模式或 TUN。[Mihomo 监听器](https://wiki.metacubex.one/config/inbound/listeners/) · [WSL 网络](https://learn.microsoft.com/windows/wsl/networking) · [Verge 持久扩展配置步骤](https://github.com/Embracecactus/wsl-agent-privacy/blob/main/claude-native/references/network.md)

~~~yaml
listeners:
  - {name: claude-private, type: http, listen: 127.0.0.1, port: 17897, proxy: CLAUDE_FIXED_NODE}
~~~

## 安装与配置

~~~bash
git clone --branch claude-bwrap --single-branch https://github.com/Embracecactus/wsl-agent-privacy.git claude-bwrap-src
cd claude-bwrap-src
/usr/bin/python3 -I claude-bwrap/install.py --target claude
guard="$HOME/.claude/skills/claude-bwrap/scripts/guard.py"
/usr/bin/python3 -I "$guard" init
~~~

隔离版沿用其早期分发配置 `~/.config/wsl-agent-privacy/config.json`。已有该文件时跳过 `init`，直接核对原配置，保留账号和历史。日常原生分支使用单独的 `~/.config/claude-native/`。

| 本机字段 | 填写内容 |
| --- | --- |
| `ports.claude`、`nodes.claude` | 当前监听端口和固定节点名，与 Mihomo 一致。样例保留原版可选 Codex 字段；只用 Claude 时将其端口保留为另一个不同的值即可 |
| `rendered_profile` | 核心实际加载的生成配置在 WSL 可读的绝对路径。含凭据的订阅、配置和 secret 保存在本机 |
| `executables.claude` | 厂商原生链接，通常是 `~/.local/bin/claude`。自更新的签名校验使用官方 versions 布局 |
| `controller` | Windows 例为 `{"windows_pipe":"verge-mihomo"}`，按本机管道名填写。Linux 可用 `{"unix_socket":"/absolute/path/to/controller.sock"}` 或本地 HTTP 端口和凭据文件。需要凭据时在同一对象加入 `secret_file`，指向权限 0600 的本机文件 |
| `timezone`、`locale` | 私有进程与其系统时区文件所用的值，分发默认 `Etc/UTC` 和 `C.UTF-8` |
| `project_roots` | 需要在家目录之外运行时，加入具体业务项目的绝对路径。会话对当前工作项目有写权限 |

在 Windows PowerShell 运行以下命令可以列出正在运行的 Verge 核心管道，将对应实例的名称填入 `windows_pipe`。一次实机检查发现，生成 YAML 中的管道值与运行实例名称不同；以后若预检在 Clash 重启后失败，可先核对这里。

~~~powershell
[IO.Directory]::GetFiles('\\.\pipe\') |
    ForEach-Object { ($_ -split '\\')[-1] } |
    Where-Object { $_ -match '^verge-mihomo($|-)' }
~~~

## 验收与日常命令

~~~bash
/usr/bin/python3 -I "$guard" check claude
/usr/bin/python3 -I "$guard" entries
export PATH="$HOME/.local/share/claude-bwrap/bin:$PATH"
hash -r
type -a claude-bwrap
claude-bwrap --self-test
claude-bwrap --version
~~~

自检应显示 `proxy_tls: verified`，直接 IPv4、IPv6、UDP DNS 均无路由，临时关闭的测试监听拒绝连接。每次启动会匿名核对监听和真实节点链，中继为新连接最多复用最近 15 秒的成功复核。首次在准备给它使用的项目中运行 `claude-bwrap`。希望新终端也能使用时，把上面的 PATH 行保存至个人 shell 配置。已用日常版的机器上，`type -a claude` 与 `type -a claude-bwrap` 可分别确认两个入口。

## 会话、更新与撤销

私有 HOME 位于 `~/.local/state/wsl-agent-privacy/claude`。从早期隔离版迁移时复用已有目录；新安装首次启动可能需要登录。当前业务目录以相同路径挂载。需要 WSLg 或限定的 Windows 工具时，逐项查看相应配置。[会话与权限](sessions.md) · [Windows 工具](windows.md)

手动升级用 `claude-bwrap update` 或 `claude-bwrap upgrade`。受管流程核对官方签名和校验和，成功后切换厂商链接，再从同一命令检查版本。若已有其他宿主维护器接管厂商链接，升级沿用该维护器的流程。[官方签名](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)

撤销时从 shell 配置移除这个分支的 PATH 行并新开终端。在保留的同版本检出中执行 `python3 -I claude-bwrap/install.py --target claude --remove` 可移除内容匹配的 Skill。配置和私有会话目录单独保留。
