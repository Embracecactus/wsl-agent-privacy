"""HTTP CONNECT adapter for websocket clients that don't honor proxy env vars.

It accepts only a loopback HTTP proxy.  Failure to reach or tunnel through the
proxy is terminal: this adapter never falls back to a direct socket.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import inspect
import os
import re
import ssl as ssl_module
from urllib.parse import urlsplit

class ProxyError(ConnectionError): pass

def _proxy(environ=None):
    env = os.environ if environ is None else environ
    # WSS_PROXY/WS_PROXY are supplied by the bwrap guard.  Do not reinterpret
    # an unrelated desktop HTTPS_PROXY as a mandate: outside the protected
    # session, preserve the upstream client's direct behaviour.
    value = env.get('WSS_PROXY') or env.get('WS_PROXY')
    if not value: return None
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.hostname not in ('127.0.0.1', '::1') or not parsed.port:
        raise ProxyError('proxy must be an unauthenticated loopback HTTP endpoint')
    return parsed.hostname, parsed.port

async def _socket(uri, environ=None):
    target=urlsplit(uri)
    if target.scheme not in ('ws','wss') or not target.hostname: raise ProxyError('websocket URI required')
    proxy=_proxy(environ)
    if proxy is None: return None
    host,port=proxy; target_port=target.port or (443 if target.scheme=='wss' else 80)
    reader,writer=await asyncio.open_connection(host,port)
    try:
        authority=f'{target.hostname}:{target_port}'
        writer.write(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\nProxy-Connection: keep-alive\r\n\r\n'.encode('ascii'))
        await writer.drain()
        head=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),timeout=20)
        if len(head)>16384 or not re.match(rb'^HTTP/1\.[01] 200(?:\s|\r)',head): raise ProxyError('HTTP CONNECT was not accepted')
        raw=writer.get_extra_info('socket')
        if raw is None: raise ProxyError('proxy did not provide a socket')
        return raw.dup()
    finally:
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass

def _normalize_headers(websockets_module, kwargs):
    parameters=inspect.signature(websockets_module.connect).parameters
    if 'additional_headers' in kwargs and 'additional_headers' not in parameters and 'extra_headers' in parameters:
        kwargs['extra_headers']=kwargs.pop('additional_headers')
    # Newer websockets can discover proxies itself.  We already supply a
    # connected socket, so disable that second discovery path explicitly.
    if 'proxy' in parameters: kwargs['proxy']=None
    return kwargs

def _require_verified_tls(uri, kwargs):
    if urlsplit(uri).scheme != 'wss': return
    context=kwargs.get('ssl')
    if context is False: raise ProxyError('unverified TLS is not permitted in a protected session')
    if isinstance(context, ssl_module.SSLContext) and (context.verify_mode == ssl_module.CERT_NONE or not context.check_hostname):
        raise ProxyError('unverified TLS is not permitted in a protected session')

@asynccontextmanager
async def fixed_proxy_connect(websockets_module, uri, **kwargs):
    """Open a websocket only after a loopback HTTP CONNECT tunnel succeeds."""
    sock=await _socket(uri)
    if sock is None:
        # Keep ordinary environments compatible with both websockets 12
        # (extra_headers) and newer releases (additional_headers).
        async with websockets_module.connect(uri, **_normalize_headers(websockets_module, kwargs)) as ws:
            yield ws
        return
    try:
        _require_verified_tls(uri, kwargs)
        async with websockets_module.connect(uri, sock=sock, **_normalize_headers(websockets_module, kwargs)) as ws:
            yield ws
    finally:
        try: sock.close()
        except OSError: pass
