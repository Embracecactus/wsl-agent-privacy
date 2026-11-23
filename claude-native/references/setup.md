# 在 WSL2 使用日常 Claude

## 让 WSL 连到专用监听

先在 Clash Verge Rev 中应用当前订阅的专用监听，示例端口为 `127.0.0.1:17897`。[Clash 配置](network.md)

- **Windows 上运行 Clash，WSL 使用镜像网络。** 在 WSL 运行 `wslinfo --networking-mode` 查看支持该命令的 WSL 版本。Windows 11 22H2 及以上的镜像网络支持从 Linux 用 IPv4 localhost 连接 Windows 服务。
- **WSL 使用 NAT。** Windows 宿主和 Linux 的 localhost 各自独立。可把 Mihomo 部署在这个 WSL 实例，使用 Linux 回环监听和本地控制器。也可在支持的 Windows 上将 `networkingMode=mirrored` 合并到 `%UserProfile%\.wslconfig` 的 `[wsl2]` 段。本启动器核对回环监听和实际连接的源端口，直接填 Windows 网关地址不满足该接口。改 WSL 网络模式会影响该机的 WSL2 发行版；保存工作后再从 PowerShell 运行 `wsl --shutdown` 使修改生效。[Microsoft WSL 网络](https://learn.microsoft.com/windows/wsl/networking) · [.wslconfig](https://learn.microsoft.com/windows/wsl/wsl-config)

在 WSL 验证回环 TCP。成功只表示端口可连接，固定节点由后面的 guard 再验证。

~~~bash
python3 -c 'import socket; socket.create_connection(("127.0.0.1", 17897), 3).close(); print("localhost OK")'
~~~

## 安装与绑定

需要已安装的官方 Linux 原生 Claude Code、系统 Python 3.10+、PyYAML 和系统 CA 证书。Windows 命名管道方案还使用 WSL 互操作及 Windows PowerShell。分发版使用单独的 PATH 目录，厂商的原生链接由官方安装器维护。[Claude Code 安装](https://code.claude.com/docs/en/setup) · [官方代理配置](https://code.claude.com/docs/en/network-config)

~~~bash
git clone --branch main --single-branch https://github.com/Embracecactus/wsl-agent-privacy.git claude-native-src
cd claude-native-src
/usr/bin/python3 -I claude-native/install.py --target claude
guard="$HOME/.claude/skills/claude-native/scripts/guard.py"
/usr/bin/python3 -I "$guard" init
~~~

在 `~/.config/claude-native/config.json` 中填以下值。文件由安装流程以仅当前用户可读写的权限创建。已有配置可直接编辑。

| 字段 | 填写内容 |
| --- | --- |
| `ports.claude` | 专用 HTTP 监听的实际端口，样例为 `17897` |
| `nodes.claude` | 生效配置 `proxies` 中自己的具体 VPS 节点名，与 Clash 扩展中的 `claudeNode` 一致。启动器核对节点的 `server` 为 IP 地址 |
| `rendered_profile` | 当前核心实际加载的生成 YAML 在 WSL 可读的绝对路径。Verge 可从配置目录找到 `clash-verge.yaml`，用 `wslpath -u` 转换 Windows 路径 |
| `executables.claude` | 原生 ELF 或指向它的官方链接，常见为 `~/.local/bin/claude`。可用 `file -L ~/.local/bin/claude` 确认 |
| `controller` | Windows 例为 `{"windows_pipe":"verge-mihomo"}`，按实际管道名填写。Linux 可用 `{"unix_socket":"/absolute/path/to/controller.sock"}`，或带本机 `secret_file` 的回环 HTTP 控制器 |

在 Windows PowerShell 运行以下命令可以列出正在运行的 Verge 核心管道，将对应实例的名称填入 `windows_pipe`。一次实机检查发现，生成 YAML 中的管道值与运行实例名称不同；以后若预检在 Clash 重启后失败，可先核对这里。

~~~powershell
[IO.Directory]::GetFiles('\\.\pipe\') |
    ForEach-Object { ($_ -split '\\')[-1] } |
    Where-Object { $_ -match '^verge-mihomo($|-)' }
~~~

控制器启用了凭据时，将 `secret_file` 加在同一 `controller` 对象里，指向已有的 0600 本地文件。节点资料和控制器凭据只留在本机。用当前配置核对监听及实际握手后，再启用普通命令。

~~~bash
/usr/bin/python3 -I "$guard" check claude
/usr/bin/python3 -I "$guard" entries
export PATH="$HOME/.local/share/claude-native/bin:$PATH"
hash -r
type -t claude
type -P claude
claude-local --guard-check
claude --version
~~~

`guard.py entries` 生成 `claude` 与 `claude-local`。如果已有同名 shell 函数或别名，它的优先级高于 PATH。可以直接执行 `~/.local/share/claude-native/bin/claude --guard-check` 对照，确认后再把上面的 export 行加入个人 shell 配置。从旧双入口分发版迁移时，先用绝对路径验收新入口，再从个人 shell 配置中移除旧分发版的 PATH 行。如果厂商链接已由原有宿主维护器管理，继续沿用该部署，或将独立安装的 `executables.claude` 指向明确的官方 ELF。从业务目录运行 `claude` 即可沿用原有会话和项目。更新走官方 CLI 的原生更新流程。

## 本机环境与撤销

启动器只给本次进程树设置大小写 HTTP/HTTPS/ALL/WS 代理变量，回环放入 NO_PROXY。通过 WSLENV 将对应变量转发给新建的 Windows 子程序。已经运行的 GUI 或忽略代理的工具使用各自的网络路径。分发版沿用调用者的时区和语言。需要单次进程时区时可用 `TZ=Etc/UTC claude`，系统的 `/etc/localtime` 和 `/etc/timezone` 仍是 WSL 的文件。

撤销时移除个人 shell 配置中这一条原生 PATH 并新开终端。如果要移除安装的 Skill，在同版本检出中执行 `python3 -I claude-native/install.py --target claude --remove`。旧双入口部署和另一个分支使用自己的安装路径。
