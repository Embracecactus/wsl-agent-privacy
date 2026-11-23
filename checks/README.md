# 复验

在仓库根目录运行。网络空间测试依赖已修复的 bubblewrap、iproute2、允许的用户命名空间以及系统 Python 的 PyYAML。下列夹具使用本地配置和临时目录。

~~~bash
/usr/bin/python3 -I checks/test_guards.py
/usr/bin/python3 -I checks/test_claude_modes.py
/usr/bin/python3 -I checks/verify_dns.py network/mihomo.example.yaml claude CLAUDE_FIXED_NODE
/usr/bin/python3 -I checks/verify_dns.py network/mihomo.example.yaml codex CODEX_FIXED_NODE
~~~

第一项检查固定配置、同链路不同入站的拒绝、缓存起点和真实网络命名空间内的客户端启动。临时 CLI 清除 TZ 后检查系统回退值。三种错误配置分别验证拒绝启动。第二项在临时 HOME 中检查原生与隔离入口切换、保留已有选择、拒绝覆盖用户文件、原生程序的环境与参数，以及代理预检失败时停止启动。DNS 命令可对实际加载的生成配置做同样的只读核对，输出仅有覆盖数量。

已有 Linux Mihomo 可执行文件时，以下命令在一次性网络空间只启用 loopback，自建 DNS、固定和普通代理入口及测试对端。实验包含 DNS 阳性对照与节点关闭时的新域名请求。传入程序的绝对路径。

~~~bash
unshare --user --map-current-user --keep-caps --net -- sh -c 'ip link set lo up && exec /usr/bin/python3 -I checks/check_mihomo_ingress.py "$1"' sh /path/to/mihomo
~~~

Windows 上安装 Chrome 和 Node.js 后，用普通终端运行浏览器回归。它用相邻源码的控制器和一次性 profile，不读取登录 Cookie。也可把已部署控制器文件的绝对路径作为单独参数传入，此项分发验收以 UTC 为期望值。

~~~powershell
node .\checks\browser_regression.cjs
~~~

测试页面、跨源 iframe 和 worker 的时区、冬夏偏移、WebRTC，以及 HTTP/HTTPS 代理中的目标域名和断线。仓库版使用同一控制器在 Linux Chromium 的隔离网络上完成过上述 9 项，Windows 的快捷方式、命名管道和本机应用仍在接收者的 Windows 上单独验收。

配音适配器的离线测试需使用装有 websockets 的 Python 环境。默认只连接本机回声服务，不消耗配音额度。

~~~bash
python3 integrations/test_tts_proxy_adapter.py
~~~

`reference/private_home.py` 和 `reference/browser_broker.py` 展示现场版的单份会话共享、工作目录和登录域名授权。移植时需要接收者自己的启动器布局。原部署中的个人 hook 目录、账号目录内容、Windows 配置、真实设备资料及检查回执没有分发。

## 2026-11-18 UTC 分发验证

便携入口的离线回归通过；Mihomo v1.19.33 在独立网络空间的 6 项对照、Linux Chromium 151 的 9 项浏览器检查都通过。两个 DNS 样例分别覆盖 4 和 6 个后缀，WebSocket 本地回声与代理失联检查通过。20 个 Skill 成员生成的两份 ZIP 逐字节一致，在空 HOME 安装到两端、重复安装和移除均成功。此处记录的是临时环境的结果；专用 Windows 快捷方式、登录和真实手机仍需目标机验收。
