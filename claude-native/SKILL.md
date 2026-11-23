---
name: claude-native
description: 配置和验证 WSL2 原生 Claude Code 的专用代理、Clash Verge Rev 规则、系统代理和 TUN。
---

# 日常 Claude

在本机项目中使用官方 Claude Code，沿用当前 WSL 的文件、工具和会话。

1. 根据实际放置核心的位置，按[WSL2 安装说明](references/setup.md)核对回环可达性、原生 ELF 和控制器。
2. 按[Clash 配置与模式](references/network.md)选择专用监听、规则和 TUN，补充设置放在当前订阅或本地配置中。
3. 用 `claude-local --guard-check` 检查实际连接。程序忽略代理时另查宿主的 TUN 接管及命中规则。报告区分启动检测和工具自身连接。
