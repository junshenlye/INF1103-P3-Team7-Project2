"""Local HTTP provider fixture; production clients and fakes share one dispatcher."""

from http.server import BaseHTTPRequestHandler

import httpx


class ProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content = self.rfile.read(int(self.headers["Content-Length"]))
        request = httpx.Request(
            "POST",
            "http://provider" + self.path,
            content=content,
            headers=dict(self.headers),
        )
        response = self.server.dispatch(request)
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response.content)))
        self.end_headers()
        try:
            self.wfile.write(response.content)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected when a bounded consumer rejects an oversized body.

    def log_message(self, *args):
        pass
