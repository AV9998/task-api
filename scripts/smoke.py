"""Exercise a deployed service, including authentication and task lifecycle."""
import json
import os
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base = os.getenv("BASE_URL", "http://127.0.0.1:18080")


def call(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base + path, json.dumps(data).encode() if data is not None else None, headers, method=method)
    with urlopen(request, timeout=5) as response:
        return response.status, json.load(response)


for attempt in range(30):
    try:
        if call("GET", "/health")[0] == 200:
            break
    except (URLError, HTTPError):
        time.sleep(2)
else:
    sys.exit("health check failed")

username = "ci_" + secrets.token_hex(6)
password = secrets.token_urlsafe(24)
assert call("POST", "/register", {"username": username, "password": password})[0] == 201
token = call("POST", "/login", {"username": username, "password": password})[1]["token"]
task = call("POST", "/tasks", {"title": "Deployment check"}, token)[1]
assert call("PUT", f'/tasks/{task["id"]}', {"done": True}, token)[1]["done"]
assert any(item["id"] == task["id"] for item in call("GET", "/tasks", token=token)[1]["tasks"])
assert call("DELETE", f'/tasks/{task["id"]}', token=token)[0] == 200
print("Deployment smoke test passed")
