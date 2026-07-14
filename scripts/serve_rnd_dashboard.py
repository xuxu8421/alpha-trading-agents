#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "workbench"
PORT = 8765


class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if self.path.endswith(".html") or self.path == "/":
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve Alpha R&D dashboard")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    with ReusableTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"R&D dashboard: http://127.0.0.1:{args.port}/alpha_rnd_dashboard.html")
        httpd.serve_forever()
