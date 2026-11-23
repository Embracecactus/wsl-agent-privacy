# 日常原生版复验

从本分支根目录运行。Python 使用系统 PyYAML，JavaScript 使用 Node.js。入口测试在临时 HOME 核对生成的命令、配置权限、CLI 参数、代理环境和预检失败时停止启动。扩展脚本测试分别检查默认监听与可选分流配置，覆盖已有规则和 DNS 的保留、重复应用以及端口冲突。

~~~bash
/usr/bin/python3 -IB checks/test_native.py
node checks/test_clash_profile.cjs
/usr/bin/python3 -IB checks/verify_dns.py claude-native/network/mihomo.example.yaml claude CLAUDE_FIXED_NODE
~~~

## 复现三种 Clash 模式

准备本机 Linux 版 Mihomo、iproute2 和支持非特权网络命名空间的内核。在临时网络空间中只启用 loopback，测试程序自建 DNS、固定节点、普通入口和目标服务。

~~~bash
unshare --user --map-current-user --keep-caps --net -- sh -c 'ip link set lo up && exec /usr/bin/python3 -IB checks/check_mihomo_ingress.py "$1"' sh /absolute/path/to/mihomo
~~~

2026-11-23 在 Mihomo v1.19.33 通过全部 10 项。Rule 下专用监听按绑定节点走，普通监听按域名规则走。对照组把 GLOBAL 选为 DIRECT，切换到 Global 和 Direct 后，专用监听仍走固定节点，普通监听都改走直连。另测了新主机名的解析、普通 DNS 阳性对照和固定节点关闭。该夹具通过本地代理入口验证核心分流。Windows TUN 驱动、具体应用是否被接管，需在使用它的机器上观察实际连接。[Clash 操作与验收](../claude-native/references/network.md)

## 分发入口的实机检查

2026-11-23 使用临时 HOME 安装分发包，连接已经运行的 Windows Clash，`claude --guard-check` 通过，`claude --version` 返回官方 Claude Code 2.1.330。配置使用运行实例的命名管道。正式主机的网络开关保持原值，验证止于匿名 TLS 和版本查询。

## 安装包与历史

`python3 -I make_package.py claude-native /tmp/claude-native.zip` 只打包安装器清单里的日常版文件。可在空 HOME 用 `claude-native/install.py --target claude` 安装，然后用同一份源加 `--remove` 验证撤销。[WSL 安装](../claude-native/references/setup.md) · [版本日志](../CHANGELOG.md)

两份 ZIP 分别重复构建后逐字节一致，日常版含 10 个文件，隔离版含 21 个。以两种顺序从 ZIP 安装，并交换两条 PATH 的先后顺序，`claude` 与 `claude-local` 均指向原生版，`claude-bwrap` 指向隔离版。分别移除一个 Skill 后，另一份安装仍完整。
