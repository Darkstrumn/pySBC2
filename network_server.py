import json
import socket
import socketserver
import threading
import time


class _ClientHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.request.settimeout(1.0)
        self.server._add_client(self.request)
        self.server._send_to(self.request, {"type": "hello", "timestamp_ms": int(time.time() * 1000)})

    def handle(self):
        while not self.server._stopping:
            try:
                data = self.request.recv(1)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break

    def finish(self):
        self.server._remove_client(self.request)


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class NetworkEventServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self._clients = set()
        self._lock = threading.Lock()
        self._stopping = False
        self._server = _ThreadedTCPServer((self.host, self.port), _ClientHandler)
        self._server._add_client = self._add_client
        self._server._remove_client = self._remove_client
        self._server._send_to = self._send_to
        self._server._stopping = False
        self._thread = None

    def start(self):
        self._server._stopping = False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self._server._stopping = True
        self._server.shutdown()
        self._server.server_close()

    def publish(self, payload):
        payload = dict(payload)
        payload.setdefault("timestamp_ms", int(time.time() * 1000))
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.sendall(data)
            except OSError:
                self._remove_client(client)

    def _send_to(self, client, payload):
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            client.sendall(data)
        except OSError:
            self._remove_client(client)

    def _add_client(self, client):
        with self._lock:
            self._clients.add(client)

    def _remove_client(self, client):
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)
        try:
            client.close()
        except OSError:
            pass
