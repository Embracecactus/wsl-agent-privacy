#!/usr/bin/env python3
"""Offline CONNECT regression; no vendor call, account data, or user text."""
import argparse, asyncio, os, pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import websockets
from wsl_tts_proxy import fixed_proxy_connect
async def relay(reader,writer):
    line=await reader.readline(); headers=[]
    while True:
        h=await reader.readline()
        if h in (b'\r\n',b''): break
        headers.append(h)
    assert line.startswith(b'CONNECT 127.0.0.1:')
    host,port=line.split()[1].decode().rsplit(':',1)
    up_r,up_w=await asyncio.open_connection(host,int(port)); writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n'); await writer.drain()
    async def copy(a,b):
        try:
            while x:=await a.read(65536): b.write(x); await b.drain()
        finally: b.close()
    await asyncio.gather(copy(reader,up_w),copy(up_r,writer),return_exceptions=True)
async def echo(ws):
    async for value in ws: await ws.send(value)
async def main(public=False):
    server=await websockets.serve(echo,'127.0.0.1',0); port=server.sockets[0].getsockname()[1]
    proxy=await asyncio.start_server(relay,'127.0.0.1',0); proxy_port=proxy.sockets[0].getsockname()[1]
    env=os.environ.copy(); env['WSS_PROXY']=f'http://127.0.0.1:{proxy_port}'
    old=os.environ.copy(); os.environ.update(env)
    try:
        async with fixed_proxy_connect(websockets,f'ws://127.0.0.1:{port}/') as ws:
            await ws.send('probe'); assert await ws.recv()=='probe'
        os.environ['WSS_PROXY']='http://127.0.0.1:1'
        try: await fixed_proxy_connect(websockets,f'ws://127.0.0.1:{port}/').__aenter__()
        except OSError: pass
        else: raise AssertionError('closed proxy unexpectedly connected')
        if public:
            # Anonymous upgrade only: no message, client identity, user text,
            # or vendor-specific query parameters are sent.
            # Fall back to the protected session's WSS_PROXY, not this test's
            # local fixture.  Outside that session this test is intentionally
            # unavailable rather than trying a direct connection.
            if old.get('WSS_PROXY'): os.environ['WSS_PROXY']=old['WSS_PROXY']
            else: os.environ.pop('WSS_PROXY',None)
            if not os.environ.get('WSS_PROXY'):
                raise RuntimeError('public upgrade requires protected WSS_PROXY')
            async with fixed_proxy_connect(websockets,'wss://ws.postman-echo.com/raw'):
                pass
        print('{"offline_connect_proxy":true,"direct_fallback":false,"tls_modified":false,"public_upgrade":%s}' % ('true' if public else 'false'))
    finally:
        os.environ.clear(); os.environ.update(old); proxy.close(); await proxy.wait_closed(); server.close(); await server.wait_closed()
parser=argparse.ArgumentParser(); parser.add_argument('--public-upgrade',action='store_true')
asyncio.run(main(parser.parse_args().public_upgrade))
