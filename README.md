# WSL2 中 Claude Code 的网络与工具隐私

这套防护让 Claude Code 和它的 Linux 子进程只能通过经核验的本地代理访问网络。代理失联时，新连接会失败。普通入口仍叫 `claude`，Codex 可选。专用 Windows Chrome 使用独立数据目录，项目文件和选定的 Windows 工具有各自的权限边界。

首次排查、采用的措施和实验结果集中在[完整措施与验收记录](PROTECTION.md)。本机可以验证进程的出口、文件视图和工具返回。账号状态以服务商通知为准。[Anthropic 账号通知与申诉](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals) · [服务支持地区](https://www.anthropic.com/legal/supported-regions)

## 从这里开始

在普通 WSL 终端进入本仓库，先安装 Claude 的只读审计 Skill。需要 Codex 时将 `--target claude` 换成 `--target both`。

~~~bash
python3 -I wsl-agent-privacy/install.py --target claude
python3 -I ~/.claude/skills/wsl-agent-privacy/scripts/audit.py host
~~~

安装 Skill 后，在 Claude 中输入 `/wsl-agent-privacy`。启用网络隔离是单独一步，需要使用者自己的 Mihomo 专用监听、已加载的生成配置和原生 CLI，步骤含验收和撤销。[WSL 安装](wsl-agent-privacy/references/setup.md) · [Mihomo 局部合并样例](network/mihomo.example.yaml)

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
