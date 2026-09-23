"""Forward Alertmanager notifications to the configured team webhook."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


class Relay(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/alerts" or size < 1 or size > 262144:
            self.send_error(400)
            return
        data = self.rfile.read(size)
        try:
            request = Request(os.environ["ALERT_WEBHOOK_URL"], data, {"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=10) as response:
                status = 200 if 200 <= response.status < 300 else 502
        except Exception:  # Relay reports failure so Alertmanager retries the notification.
            status = 502
        self.send_response(status)
        self.end_headers()


if __name__ == "__main__":
    if not os.getenv("ALERT_WEBHOOK_URL", "").startswith("https://"):
        raise RuntimeError("ALERT_WEBHOOK_URL must be HTTPS")
    ThreadingHTTPServer(("0.0.0.0", 8001), Relay).serve_forever()  # nosec B104: container network listener
