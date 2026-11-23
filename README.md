# WSL2 中 Claude Code 的网络与工具隐私

日常输入 `claude`，在本机 WSL 的工作目录和 HOME 中使用官方 Claude Code。启动器先核对专用代理和固定节点，检查通过才启动。需要隔离时输入 `claude-bwrap`，保留私有文件视图、Linux 网络命名空间和中继。专用 Windows Chrome 使用独立数据目录。

| 命令 | 工作环境 | 网络范围 |
| --- | --- | --- |
| `claude` 或 `claude-local` | 本机用户的项目、历史和工具 | 启动时实测固定节点。遵守代理的程序使用该出口，其他本机进程仍可能直连。 |
| `claude-bwrap` | 按隔离规则挂载项目和获准的接口 | 命名空间内的 Linux 进程经中继出网，代理失联时新连接失败。 |

旧安装的默认模式可显式切换。各阶段的来源、可取回的旧源码和分发版本见[开发日志](CHANGELOG.md)。

已有早期宿主部署、并保留原 `runtime/install_runtime.py` 及其配套源码时，可从本仓库执行 `python3 -IB integrations/install_claude_modes.py /path/to/runtime native`。末尾改成 `bwrap` 即可切回。该适配器复用已有宿主代理检查和签名升级机制。下面的分发版安装步骤适用于新机器。

首次排查、采用的措施和实验结果集中在[完整措施与验收记录](PROTECTION.md)。本机可以验证进程的出口、文件视图和工具返回。账号状态以服务商通知为准。[Anthropic 账号通知与申诉](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals) · [服务支持地区](https://www.anthropic.com/legal/supported-regions)

## 从这里开始

在普通 WSL 终端进入本仓库，先安装 Claude 的只读审计 Skill。需要 Codex 时将 `--target claude` 换成 `--target both`。

~~~bash
python3 -I wsl-agent-privacy/install.py --target claude
python3 -I ~/.claude/skills/wsl-agent-privacy/scripts/audit.py host
~~~

安装 Skill 后，在 Claude 中输入 `/wsl-agent-privacy`。配置好自己的 Mihomo 专用监听、已加载的生成配置和原生 CLI 后，用 `guard.py entries --claude-native` 生成日常入口。首次启用及旧版更新步骤见[WSL 安装](wsl-agent-privacy/references/setup.md)和[Mihomo 局部合并样例](network/mihomo.example.yaml)。

| 需要完成的工作 | 可用材料 |
| --- | --- |
| 网络、DNS、VPS 维护、连接超时 | [分流与 DNS](wsl-agent-privacy/references/network.md) · [离线 Mihomo 实验](checks/check_mihomo_ingress.py) |
| Windows 专用快捷方式、时区和受控工具 | [Windows 操作](wsl-agent-privacy/references/windows.md) · [浏览器验收](checks/browser_regression.cjs) |
| 会话、工具文本、GitHub 权限和跨工具读取 | [会话与权限](wsl-agent-privacy/references/sessions.md) · [文件授权参考](reference/private_home.py) |
| 日常入口、退出、升级、临时观察 | [运行与故障](wsl-agent-privacy/references/operations.md) · [问题索引](wsl-agent-privacy/references/topics.md) |
| 应用的 WebSocket 配音连接 | [代理适配器](integrations/wsl_tts_proxy.py) · [离线测试](integrations/test_tts_proxy_adapter.py) |

可以从本地源码生成确定性的 Skill ZIP。归档仅收录安装器显式列出的文件。

~~~bash
python3 -I make_package.py wsl-agent-privacy wsl-agent-privacy.zip
~~~
