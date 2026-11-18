# 浏览器与 Windows

## 专用 Chrome

专用 Claude Chrome 应使用独立 profile 和单独快捷方式，设置本地专用代理，禁用 QUIC 与非代理 WebRTC UDP，并将语言和时区控制限制在该实例。关闭或失去代理时页面应得到代理错误，测试服务器不应收到直连请求。

验证页面、iframe、worker、shared worker 和 service worker 的语言与时区，另检查 WebRTC 是否产生候选地址。只改变 Chrome 参数不会改变 Windows 系统时区，也不会移除已安装中文字体、操作系统 emoji 风格或网页能观察到的全部特征。网页“风险分”是启发式信号，不能当作 Claude 的官方风控评分。

普通 Chrome、游戏和国内应用保持使用自己的 profile、系统代理和规则。专用浏览器的防火墙规则若按全局 Chrome 二进制路径创建，会影响普通 Chrome。Windows 桌面版 Claude、WSL Claude 和浏览器 Claude 是不同入口，分别验证。

Windows 端需要标准安装的 Chrome、Node.js 和 WSL。把 scripts/chrome.ps1 与同目录的 browser_controller.cjs 一起放在可从 Windows 访问的本地目录。先在 WSL 安装 Skill 并验收固定出口。PowerShell 默认使用当前 WSL 发行版，也接受 -Distribution 选择已配置的发行版。

~~~powershell
.\scripts\chrome.ps1 -Mode check
.\scripts\chrome.ps1 -Mode launch -Url https://claude.ai/login
~~~

桌面快捷方式可指向 powershell.exe，参数为 -NoProfile -File 加上述脚本的完整路径和 -Mode launch。启动脚本复核 WSL 专用监听、配置与实测链路后，把核实过的端口交给 Windows 控制器。独立 profile 位于 LocalAppData 下的 WslAgentPrivacyBrowser。控制器与 Chrome 使用私有调试管道，Windows 实例之间通过具备随机令牌的本地命名管道通信。浏览器关闭时控制器退出。

## 时区、语言和翻译

分发版使用 UTC 作为浏览器专用时区，默认拒绝网页地理位置权限。控制器在导航前校验时区和语言，并对新页面、iframe 和 worker 类目标初始化。WSL 的系统文件、子进程环境与 Windows 页面由不同组件负责。网页仍可能根据账户偏好、站点数据或站点策略显示中文。可用仓库中的 checks/browser_regression.cjs 测试页面、跨源 iframe、worker 的时区名和冬夏分钟偏移。这个检查在本地代理和临时 profile 中运行。

Chrome 自动翻译、云端翻译和本地翻译会把页面或输入提供给相应翻译服务或本地模型。若只是为了日常中文互动，直接使用中文不会改变代理出口。翻译取舍应以内容隐私、可读性和工具兼容性决定，不应以无法证实的风险分驱动。

网页对时区、语言、字体、Intl 地区、偏移和 emoji 打的分数由该网页自行定义。网页测到的 JavaScript 环境与 WSL 内的 CLI 是两套进程。关于日期分隔符、Unicode 变体或中转域名的猜测，需要对应客户端版本的独立证据；页面分数无法说明云端采用了哪种判定。

## 产品边界

Windows Claude Desktop、其 VM 或旧任务数据，专用 Chrome 网页、Windows 原生 CLI 与 WSL CLI 各有安装、会话、网络和更新路径。卸载 Desktop 或清理 VM 不会改变 WSL CLI 的网络命名空间。保留数据前先确认旧会话是否需要恢复，清理后只报告实际删除或保留的范围。

## WSL 调用 Windows

一个 WSL Agent 调用 PowerShell、COM、Blender、Office、模拟器或 adb.exe 时，工具输出会返回云端 Agent。代理不能抹去 stdout 中的 IP、时区、用户目录、设备序列号、媒体 EXIF、文件名或文档内容。

按能力建立窄 broker。它应只允许经过验证的可执行文件、必要参数和固定代理环境，并输出最少结果。Windows 进程自身的网络仍由 Windows 侧策略控制，WSL 网络命名空间不能覆盖它。

可兼容的能力包括登录浏览器、一个 Wayland socket、受限 USB ADB、特定导出程序。每增加一项，记录程序、动作、输入、输出和网络出口。不要开放通用 PowerShell、CMD、Windows 目录、全局 WSL 互操作或局域网作为“兼容”。

## WSLg、ADB 与宿主边界

便携版在 config.json 的 wayland 为 true 时才共享单个 socket。需要实际 USB 业务时，可在同一配置增加 usb_adb。exe 填 WSL 中可见的 Windows SDK adb.exe 绝对路径，sha256 对象填 adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll 三个文件各自经可信安装来源核对的 SHA-256。在包含三个文件的 SDK 目录，可本地运行以下命令。

~~~bash
sha256sum adb.exe AdbWinApi.dll AdbWinUsbApi.dll
~~~

运行器用固定程序和哈希启动专用 broker。支持 adb version、adb devices、限定的 getprop 和明确请求的截图，设备列表使用 usb-N 别名；如需在已批准的实体设备安装当前项目 APK，还须在 usb_adb 中显式设置 allow_project_apk_install 为 true。通用 PowerShell、Blender 任意脚本、Office COM、网络 ADB 和模拟器都需要独立的业务接口。设备截图、属性和业务产物仍有实际内容，读取前按具体任务决定。

单个 Wayland socket 可以支持图形程序。X11、音频、麦克风、GPU、Windows 注册表和完整 WSLg 树应另行评估。USB ADB 限制的是 WSL 到设备的命令通道，无法限制手机自身通过 Wi-Fi 或蜂窝网访问外部服务。

检查启动器引用的 broker、浏览器脚本和 shell 启动文件是否位于不可替换路径。只读子目录的父目录仍可写时，目录替换和新增启动文件会改变后续宿主执行链。不要把 HOME 整体可写再把少数子目录标为只读视作完整文件隔离。
