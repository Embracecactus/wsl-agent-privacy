#!/usr/bin/python3 -I
"""Start Claude only after checking its dedicated Windows proxy listener."""
import http.client
import json
import os
import pathlib
import socket
import ssl
import subprocess
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
PS = '/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe'
WSLPATH = '/usr/bin/wslpath'


def bridge(request):
    win_script = subprocess.check_output(
        [WSLPATH, '-w', str(HERE / 'windows_bridge.ps1')], text=True
    ).strip()
    result = subprocess.run([PS, '-NoLogo', '-NoProfile', '-NonInteractive',
                             '-ExecutionPolicy', 'Bypass', '-File', win_script],
                            input=json.dumps(request).encode(), capture_output=True, timeout=35)
    try:
        answer = json.loads(result.stdout.decode('utf-8-sig'))
    except (UnicodeError, ValueError):
        raise RuntimeError('Windows Clash 检查没有返回有效结果') from None
    if result.returncode or answer.get('ok') is False:
        raise RuntimeError('Windows Clash 检查失败：' + answer.get('stage', 'unknown'))
    return answer


def check(settings, start_if_missing=True):
    port, node = settings['port'], settings['node']
    status = bridge({'action': 'status', 'start_if_missing': start_if_missing,
                     'port': port, 'node': node})
    if status.get('node_type') != settings['node_type']:
        raise RuntimeError('专用节点不存在或类型发生变化；拒绝启动')
    listeners = status.get('listeners', [])
    if len(listeners) != 1 or listeners[0] != {'address': '127.0.0.1', 'owner': 'verge-mihomo'}:
        raise RuntimeError('Clash 专用本机端口未就绪；拒绝使用普通端口或直连')

    # This anonymous TLS handshake checks reachability; it does not invoke a model.
    c = http.client.HTTPSConnection('127.0.0.1', port, timeout=8,
                                     context=ssl.create_default_context())
    c.set_tunnel('api.anthropic.com', 443)
    try:
        c.connect()
        source_port = c.sock.getsockname()[1]
        route = bridge({'action': 'connection', 'source_port': source_port})
        matches = route.get('matches', [])
        if len(matches) != 1 or matches[0].get('chains') != [node]:
            raise RuntimeError('实测连接没有使用指定节点；拒绝启动')
    finally:
        c.close()
    return status


def launch_environment(settings):
    proxy = f"http://127.0.0.1:{settings['port']}"
    browser = str(pathlib.Path.home() / '.local/bin/claude-guard-browser')
    overrides = {
        'HTTP_PROXY': proxy, 'HTTPS_PROXY': proxy, 'http_proxy': proxy, 'https_proxy': proxy,
        'ALL_PROXY': proxy, 'all_proxy': proxy,
        'WS_PROXY': proxy, 'WSS_PROXY': proxy, 'ws_proxy': proxy, 'wss_proxy': proxy,
        'NO_PROXY': 'localhost,127.0.0.1,::1', 'no_proxy': 'localhost,127.0.0.1,::1',
        'BROWSER': browser, 'GH_BROWSER': browser,
        'NODE_USE_ENV_PROXY': '1',
        'TZ': 'America/Los_Angeles', 'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8',
        'DISABLE_TELEMETRY': '1',
        'DISABLE_ERROR_REPORTING': '1',
        'DISABLE_FEEDBACK_COMMAND': '1',
        'HYPERFRAMES_NO_TELEMETRY': '1',
    }
    # Win32 children do not inherit ordinary WSL exports. Forward proxy URLs
    # verbatim, in this launch tree only; path translation would corrupt them.
    shared = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'WS_PROXY', 'WSS_PROXY', 'NO_PROXY',
              'NODE_USE_ENV_PROXY')
    retained = [entry for entry in os.environ.get('WSLENV', '').split(':')
                if entry and entry.split('/', 1)[0].upper() not in shared]
    overrides['WSLENV'] = ':'.join([*retained, *(name + '/w' for name in shared)])
    return overrides


def main():
    args = sys.argv[1:]
    settings = json.loads((HERE / 'guard.json').read_text())
    browser_mode = pathlib.Path(sys.argv[0]).name == 'claude-guard-browser'
    if browser_mode:
        if len(args) != 1 or urllib.parse.urlsplit(args[0]).scheme != 'https':
            raise RuntimeError('登录浏览器只接受一个 HTTPS 地址')
        check(settings)
        bridge({'action': 'browser', 'port': settings['port'], 'node': settings['node'], 'url': args[0]})
        return
    if args == ['--guard-check']:
        result = check(settings, start_if_missing=False)
        print(f"Claude 专用代理检查通过：127.0.0.1:{settings['port']}，固定节点连接正常（Clash {result['mode']} 模式）")
        return
    if any(arg == '--settings' or arg.startswith('--settings=') for arg in args):
        raise RuntimeError('启动器需要 --settings 固定代理；额外配置请放在用户或项目设置文件中')
    check(settings)
    overrides = launch_environment(settings)
    env = dict(os.environ, **overrides)
    real = pathlib.Path.home() / '.local/bin/claude'
    if not real.is_file():
        raise RuntimeError('未找到已安装的官方 Claude 可执行文件')
    print(f"[claude-guard] 专用代理已验证：127.0.0.1:{settings['port']}", file=sys.stderr)
    os.execve(real, [str(real), '--settings', json.dumps({'env': overrides}), *args], env)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, http.client.HTTPException,
            subprocess.SubprocessError) as exc:
        # Exceptions from subprocess.run must not echo arguments (which may include a login URL).
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print('[claude-guard] ' + message + '；未启动 Claude。', file=sys.stderr)
        sys.exit(1)
