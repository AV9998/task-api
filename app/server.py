"""Small dependency-free task API with SQLite persistence and metrics."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DB_PATH = os.getenv("DB_PATH", "/data/tasks.db")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "")
COUNTS = {}


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, digest TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    connection.commit()
    return connection


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240000).hex()


def token_for(user_id, expiry=None):
    expiry = expiry or int(time.time()) + 3600
    payload = f"{user_id}.{expiry}"
    signature = hmac.new(TOKEN_SECRET.encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}.{signature}"


def user_from_token(header):
    if not header.startswith("Bearer "):
        return None
    try:
        identifier, expires, signature = header[7:].split(".")
        payload = f"{identifier}.{expires}"
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), "sha256").hexdigest()
        if int(expires) <= time.time() or not hmac.compare_digest(signature, expected):
            return None
        return int(identifier)
    except (ValueError, TypeError):
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        print(json.dumps({"event": "http", "message": format_string % args}), flush=True)

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        key = (self.command, status)
        COUNTS[key] = COUNTS.get(key, 0) + 1

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16384:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data

    def handle_request(self):
        path = urlsplit(self.path).path
        if self.command == "GET" and path == "/health":
            with connect() as db:
                db.execute("SELECT 1")
            return self.reply(200, {"status": "ok"})
        if self.command == "GET" and path == "/metrics":
            lines = ["# TYPE task_http_requests_total counter"]
            for (method, code), count in sorted(COUNTS.items()):
                lines.append(f'task_http_requests_total{{method="{method}",code="{code}"}} {count}')
            body = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.command == "POST" and path in ("/register", "/login"):
            data = self.body()
            username, password = data.get("username"), data.get("password")
            if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_]{3,32}", username) or not isinstance(password, str) or len(password) < 12:
                return self.reply(400, {"error": "username must be 3-32 letters/digits/underscores and password at least 12 characters"})
            with connect() as db:
                if path == "/register":
                    salt = secrets.token_hex(16)
                    try:
                        db.execute("INSERT INTO users(username,salt,digest) VALUES(?,?,?)", (username, salt, password_digest(password, salt)))
                    except sqlite3.IntegrityError:
                        return self.reply(409, {"error": "username unavailable"})
                    return self.reply(201, {"created": True})
                row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                if row is None or not hmac.compare_digest(row["digest"], password_digest(password, row["salt"])):
                    return self.reply(401, {"error": "invalid credentials"})
                return self.reply(200, {"token": token_for(row["id"])})
        user_id = user_from_token(self.headers.get("Authorization", ""))
        if user_id is None:
            return self.reply(401, {"error": "authentication required"})
        match = re.fullmatch(r"/tasks/([1-9][0-9]*)", path)
        if path != "/tasks" and not match:
            return self.reply(404, {"error": "not found"})
        with connect() as db:
            if path == "/tasks" and self.command == "GET":
                rows = db.execute("SELECT id,title,done FROM tasks WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
                return self.reply(200, {"tasks": [dict(id=r["id"], title=r["title"], done=bool(r["done"])) for r in rows]})
            if path == "/tasks" and self.command == "POST":
                title = self.body().get("title")
                if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
                    return self.reply(400, {"error": "title must be 1-200 characters"})
                cursor = db.execute("INSERT INTO tasks(user_id,title) VALUES(?,?)", (user_id, title.strip()))
                return self.reply(201, {"id": cursor.lastrowid, "title": title.strip(), "done": False})
            if match:
                task_id = int(match.group(1))
                row = db.execute("SELECT id,title,done FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
                if row is None:
                    return self.reply(404, {"error": "not found"})
                if self.command == "DELETE":
                    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
                    return self.reply(200, {"deleted": True})
                if self.command == "PUT":
                    data = self.body()
                    title, done = data.get("title", row["title"]), data.get("done", bool(row["done"]))
                    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or not isinstance(done, bool):
                        return self.reply(400, {"error": "invalid title or done"})
                    db.execute("UPDATE tasks SET title=?,done=? WHERE id=? AND user_id=?", (title.strip(), int(done), task_id, user_id))
                    return self.reply(200, {"id": task_id, "title": title.strip(), "done": done})
        return self.reply(405, {"error": "method not allowed"})

    def do_GET(self):
        self.safe_handle()

    def do_POST(self):
        self.safe_handle()

    def do_PUT(self):
        self.safe_handle()

    def do_DELETE(self):
        self.safe_handle()

    def safe_handle(self):
        try:
            self.handle_request()
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {"error": "invalid request"})
        except sqlite3.Error:
            self.reply(503, {"error": "database unavailable"})


def main():
    if len(TOKEN_SECRET) < 32:
        raise RuntimeError("TOKEN_SECRET must contain at least 32 characters")
    with connect():
        pass
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()  # nosec B104: container network listener


if __name__ == "__main__":
    main()
