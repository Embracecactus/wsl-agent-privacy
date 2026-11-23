"""One-shot loopback DNS and outbound-routing experiment with a real Linux Mihomo."""
import argparse
from contextlib import ExitStack, closing
import http.client
import json
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-bwrap/scripts"))
from route import validate_match


def pinned_connection(matches, node, port):
    try:
        validate_match(matches, node, port, None)
    except RuntimeError:
        return False
    return True


class LocalDNS(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        pos, labels = 12, []
        while pos < len(data) and data[pos]:
            size = data[pos]
            labels.append(data[pos + 1:pos + 1 + size].decode("ascii"))
            pos += size + 1
        self.server.names.append(".".join(labels))
        sock.sendto(data[:2] + bytes.fromhex("81830001000000000000") + data[12:pos + 5],
                    self.client_address)


class LocalPeer(socketserver.BaseRequestHandler):
    def handle(self):
        # Record only our synthetic address in the real outbound VLESS request.
        self.request.settimeout(4)
        header = bytearray()
        while b"route-probe!" not in header and len(header) < 4096:
            chunk = self.request.recv(2048)
            if not chunk:
                return
            header.extend(chunk)
        self.server.requests.append(bytes(header))
        self.request.sendall(b"\x00\x00ok")
        try:
            self.request.recv(1)
        except TimeoutError:
            pass


def loopback_server(stack, server_class, handler):
    server = stack.enter_context(server_class(("127.0.0.1", 0), handler))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stack.callback(worker.join, 2)
    stack.callback(server.shutdown)
    return server


def get_json(controller, path):
    port, secret = controller
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=2)) as client:
        client.request("GET", path, headers={"Authorization": "Bearer " + secret})
        response = client.getresponse()
        if response.status != 200:
            raise RuntimeError("test core HTTP error")
        return json.loads(response.read())


def probe(port, host, controller):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=3)) as tunnel:
        tunnel.set_tunnel(host, 443)
        tunnel.connect()
        tunnel.sock.sendall(b"route-probe!")
        with tunnel.sock.makefile("rb") as stream:
            if stream.read(2) != b"ok":
                raise ConnectionError("upstream did not echo")
        connections = get_json(controller, "/connections")["connections"]
        match, = [c for c in connections if c["metadata"]["host"] == host]
        return {"chains": match["chains"], "specialProxy": match["metadata"]["specialProxy"],
                "inboundPort": match["metadata"]["inboundPort"]}


def run(core):
    with ExitStack() as stack:
        dns = loopback_server(stack, socketserver.UDPServer, LocalDNS)
        dns.names = []
        peer_stack = stack.enter_context(ExitStack())
        peer = loopback_server(peer_stack, socketserver.ThreadingTCPServer, LocalPeer)
        peer.requests = []
        with ExitStack() as held:
            ports = []
            for _ in range(3):
                port = held.enter_context(socket.socket())
                port.bind(("127.0.0.1", 0))
                ports.append(port.getsockname()[1])
        api, fixed, ordinary = ports
        controller = (api, uuid.uuid4().hex)
        listeners = [dict(name="fixed", type="http", listen="127.0.0.1", port=fixed, proxy="test-node"),
                     dict(name="ordinary", type="http", listen="127.0.0.1", port=ordinary)]
        config = {"external-controller": f"127.0.0.1:{api}", "secret": controller[1], "mode": "rule", "ipv6": False,
                  "listeners": listeners, "dns": {"enable": True, "enhanced-mode": "fake-ip",
                    "nameserver": [f"udp://127.0.0.1:{dns.server_address[1]}"]},
                  "proxies": [{"name": "test-node", "type": "vless", "server": "127.0.0.1",
                    "port": peer.server_address[1], "uuid": str(uuid.uuid4())}],
                  "rules": ["DOMAIN,api-check.test,test-node", "IP-CIDR,192.0.2.0/24,REJECT", "MATCH,REJECT"]}
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (folder / "config.yaml").write_text(json.dumps(config))
        proc = subprocess.Popen([str(core), "-d", str(folder)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            proc.terminate()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        stack.callback(stop)
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError("isolated core did not start")
            try:
                version = get_json(controller, "/version")["version"]
                for ready_port in (fixed, ordinary):
                    with socket.create_connection(("127.0.0.1", ready_port), timeout=0.3):
                        pass
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("isolated core timed out")
        fixed_target = "previously-unknown.test"
        pinned = probe(fixed, fixed_target, controller)
        unpinned = probe(ordinary, "api-check.test", controller)
        def denied(port, host):
            try:
                probe(port, host, controller)
            except (OSError, http.client.HTTPException):
                return True
            return False
        control = "ordinary-dns-control.test"
        rejected = denied(ordinary, control)
        peer_stack.close()
        offline = "offline-unknown.test"
        offline_denied = denied(fixed, offline)
        result = {"dns_positive_control": rejected and control in dns.names,
                  "hostname_forwarded": any(fixed_target.encode() in h for h in peer.requests),
                  "unknown_domain_local_dns_blocked": fixed_target not in dns.names,
                  "offline_denied_without_local_dns": offline_denied and offline not in dns.names,
                  "chain_alone_cannot_distinguish": pinned["chains"] == unpinned["chains"] == ["test-node"],
                  "live_inbound_pin_distinguishes": pinned_connection([pinned], "test-node", fixed)
                  and not pinned_connection([unpinned], "test-node", ordinary)}
        print(json.dumps({"version": version, "checks": result}, sort_keys=True))
        return all(result.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path)
    raise SystemExit(0 if run(parser.parse_args().core.resolve(strict=True)) else 1)
