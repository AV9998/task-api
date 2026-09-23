"""Send Alertmanager notifications to the configured Gmail inbox."""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def alert_text(payload):
    """Summarize an Alertmanager webhook event for email."""
    status = payload.get("status", "unknown").upper()
    lines = [f"Task API alert: {status}"]
    for alert in payload.get("alerts", [])[:10]:
        labels = alert.get("labels", {})
        annotation = alert.get("annotations", {})
        lines.append(f"{labels.get('alertname', 'Alert')} ({labels.get('severity', 'unknown')}): {annotation.get('summary', 'No summary')}")
    return "\n".join(lines)[:20000]


class Relay(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/alerts" or size < 1 or size > 262144:
            self.send_error(400)
            return
        try:
            text = alert_text(json.loads(self.rfile.read(size)))
            account = os.environ["ALERT_EMAIL"]
            message = EmailMessage()
            message["From"] = account
            message["To"] = account
            message["Subject"] = text.splitlines()[0]
            message.set_content(text)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=10) as smtp:
                smtp.login(account, os.environ["GMAIL_APP_PASSWORD"])
                smtp.send_message(message)
            status = 200
        except Exception:  # Relay reports failure so Alertmanager retries the notification.
            status = 502
        self.send_response(status)
        self.end_headers()


if __name__ == "__main__":
    if not os.getenv("ALERT_EMAIL") or not os.getenv("GMAIL_APP_PASSWORD"):
        raise RuntimeError("Gmail alert credentials are required")
    ThreadingHTTPServer(("0.0.0.0", 8001), Relay).serve_forever()  # nosec B104: container network listener
