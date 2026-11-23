# 监控、更新与运行故障

## 运行中监控

持续监控需要明确频率、保存期限和停机条件。每次采样关联进程 PID、网络命名空间、代理连接的源端口、目标主机、Mihomo 链路和时间。没有这些关联，控制器里的连接不能归属给某一 Claude 或 Codex 会话。

对运行中的 Claude 只做只读观察，避免重载 Clash、改代理、关闭进程或抢占终端。若需模拟断线，使用临时独立代理或窗口，并在测试后确认正式会话和普通应用仍在原状态。

Peer address: uds 显示的是本地 Unix domain socket 地址，用于客户端与本机 helper 通信，不是公网 IP。它不能用于定位用户。

## 常见症状

| 现象 | 首先检查 | 结论边界 |
| --- | --- | --- |
| Waiting for API response | 专用 guard、节点 TLS、控制器链路、VPS 和服务状态 | 可确认连接失败点，不能单凭界面确定风控 |
| 启动拒绝 | 本地监听是否只在 loopback、固定节点与匿名探测是否匹配 | 失败关闭属于预期保护行为 |
| SSLEOFError | TLS 握手、代理重载、节点稳定性，有限重试 | 不要用直连作为恢复手段 |
| Codex clipboard 或 daemon 问题 | 当前 bwrap 的可见 socket、no-daemon、Wayland 和 clipboard 依赖 | 可用性问题不代表网络泄露 |
| Claude 会话没有继续记录 | 当前目录、项目筛选、会话是否保存 | 不要把空列表当作账号或网络故障 |
| Ctrl+C 后 Python 回溯 | 外层启动器在收尾时被第二次中断 | 确认子进程和 relay 已退出，再修复清理路径 |

服务端使用窗口、配额或五小时限制会阻止新的模型请求。它和代理检查是两类证据。网络成功而服务端拒绝时，等待服务端窗口恢复，不要通过更换出口、账号或直连来绕过限制。

## 更新

从本分支的入口执行 `claude-bwrap update`，升级前后都用 `claude-bwrap --version` 检查版本。原生 Claude 更新会在版本目录写入新二进制并切换启动链接。若 bwrap 中把链接只读，更新器可能报告成功却没有切换。更新专用流程可给更新器临时入口，随后在宿主侧验证签名 manifest、平台校验和及原子链接切换。安装步骤必须在普通 WSL 终端运行，隔离会话内的只读挂载会拒绝写入。Anthropic 的签名和原生安装细节见[官方说明](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)。

Codex 更新应从实际 CLI 的官方更新命令完成，重启后检查版本、启动入口和隔离自检。不要让升级过程自动恢复普通网络、共享 daemon 或未审核的系统级代理。

## 退出与恢复

前台运行时，Ctrl+C 的含义由 CLI 决定，可能取消当前操作或退出。在 CLI 已打印用量及恢复命令后，若栈尾是 RouteGate.close 和 thread.join，说明外层启动器在清理阶段收到了 Ctrl+C。便携版在这一小段时间保护清理过程，回收 relay、broker 和套接字，再恢复原信号处理。记录实际退出码；恢复命令可在正常保护入口使用。

调用 codex resume 或 Claude 的继续命令会恢复本地保存的会话上下文。它不会恢复网络连接或改变当前代理验证。恢复前应重新通过 guard 检查。

## 可复制的最小检查

在普通 WSL 终端，从已安装的 Skill 目录运行。第一条用本机可见的进程名和 PID 帮助选定实际 CLI；避免打印包含提示词或凭据的完整命令行。

~~~bash
ps -u "$(id -u)" -o pid=,ppid=,comm=
read -rp '要观察的 CLI PID: ' agent_pid
/usr/bin/python3 -I scripts/audit.py watch --pid "$agent_pid" --interval 2 --seconds 60
~~~

持续监控可省略 --seconds，Ctrl+C 停止。分类发生变化时输出 UTC 采样记录，持续无变化时仍会定期报告。端口自定义时重复使用 --proxy-port。短连接可能落在采样间隔内，UDP、Unix socket 和权限不足的观察单独标为未解析或不可读。这个监控器没有截取 TLS 内容或读取控制器全量日志。

在普通 WSL 终端先分别运行实际启动器的 guard 检查和版本命令，再启动一个短会话。升级完成后重复版本与 guard 检查。若当前 Agent 处于 bwrap 会话，涉及更新启动器、安装规则或 Windows 互操作的命令应回到普通 WSL 终端执行，因为生产启动器目录可能只读。

不要在诊断时粘贴代理 token、控制器 secret、订阅链接、SSH 私钥、浏览器 cookie 或账号恢复链接。报告写端口类别、检查是否通过和时间即可。
