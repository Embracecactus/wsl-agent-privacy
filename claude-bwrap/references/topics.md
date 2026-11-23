# 从首次排查到升级退出的主题对照

下面按问题出现的顺序整理。这里的“运行”表示分发包附有对应程序，“核对”表示需要在使用者的真实环境观察。

| 最初遇到的问题 | 使用者能做什么 | 入口 |
| --- | --- | --- |
| WSL2 使用 Claude 会暴露什么，时区和语言是否专设 | 运行宿主快照与受保护终端自检，只给启动的进程配置语言、时区和代理 | [安装](setup.md)、[浏览器与 Windows](windows.md) |
| 代理状态里显示本地端口，peer 显示 UDS | 核对监听与真实节点链，区分进程间通信、本地公网地址与代理出口 | [网络](network.md)、[监控](operations.md) |
| 启动时 Clash 尚未准备好，使用中 VPS 维护或断线 | 缺少固定链路时拒绝启动；在运行中失去代理时验证 IPv4、IPv6 和 DNS 的实际阻断 | [安装与验收](setup.md) |
| 中文输入、翻译、网页中文、第三方六项区域分数、Chrome 专用快捷方式或闪退 | 检查独立 profile、网页语言、翻译与时区的不同来源，运行专用 Chrome 的路由检查和本机页面测试 | [浏览器与 Windows](windows.md) |
| source ~/.bashrc、没有开启聊天、continue/resume 空记录、清理后还想保存 | 核对当前 shell、实际入口、项目筛选和私有 HOME；只恢复需要的记录 | [会话](sessions.md)、[安装](setup.md) |
| Windows 应用、剪映/Blender/Office、WSLg、ADB、Desktop/Windows CLI 和桌面 VM | 区分文件写入、进程启动、网络连接和云端收到的数据；按业务启用窄接口 | [浏览器与 Windows](windows.md) |
| 工具返回项目里的时区、日期、媒体内嵌的时间偏移 或 IP；Claude 读取 Codex 会话 | 本地扫描指定会话，区分指令、工具文字和实际出站；按需给最小业务摘录 | [会话与权限](sessions.md) |
| GitHub 登录/MCP、Git SSH 和 HTTPS、国内文档临时跳过应用代理 | 区分连接由本机、浏览器还是云端发起；在隔离内验证直连失败，确认所需业务是否有独立路径 | [会话](sessions.md)、[网络](network.md) |
| Clash 模式、图标、重启恢复、国内应用/游戏、QNX 改网络 | 分别验证全局设置、TUN、规则、专用监听和受影响应用，不用图标颜色推断实际路由 | [网络](network.md) |
| DNS 工程书、fake-IP、ECS、IPv4/IPv6、VPS SSH、Magpie 与隧道 | 区分解析器、权威看到的来源、HTTPS 出口、独立的 VPS 管理通道和应用代理 | [网络](network.md) |
| 连续监控一个会话，5 小时额度、TLS EOF、API 重试或权限检查失败 | 运行按进程树的本地采样；再核对各自的服务端、控制器、客户端证据与时间窗 | [监控](operations.md) |
| awk 权限告警、减少审批、普通模式与最高权限、Cage 和 bwrap | 精确授权，独立验证外层网络边界，按 Windows 兼容需求选择文件和进程隔离 | [会话](sessions.md)、[网络](network.md) |
| apt/CLI 更新、模型切换、clipboard/daemon、Claude 更新提示成功仍是旧版 | 从正常入口核对真实版本、代理及依赖。保留版本切换和可回退边界 | [监控与故障](operations.md)、[安装](setup.md) |
| Codex 打印用量与恢复命令后，Ctrl+C 在 gate.close/thread.join 回溯 | 区分工具已结束和父进程清理，验证进程退出码、套接字清理和恢复会话 | [监控与退出](operations.md) |

长会话中误发且随即撤回的业务内容、私人地址、账号、原始日志与分享文件没有诊断依赖。分发时传递判断方法、脚本和证据边界即可。
