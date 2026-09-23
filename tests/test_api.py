import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import server


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = os.path.join(cls.temp.name, "tasks.db")
        server.TOKEN_SECRET = "test-secret-at-least-thirty-two-characters"
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def call(self, method, path, data=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self.base + path, json.dumps(data).encode() if data is not None else None, headers, method=method)
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        return response.status, json.load(response)

    def test_auth_crud_and_isolation(self):
        self.assertEqual(self.call("POST", "/register", {"username": "alice", "password": "a secure password"})[0], 201)
        self.assertEqual(self.call("POST", "/register", {"username": "bob", "password": "another password"})[0], 201)
        self.assertEqual(self.call("POST", "/login", {"username": "alice", "password": "wrong password"})[0], 401)
        alice = self.call("POST", "/login", {"username": "alice", "password": "a secure password"})[1]["token"]
        bob = self.call("POST", "/login", {"username": "bob", "password": "another password"})[1]["token"]
        self.assertEqual(self.call("GET", "/tasks")[0], 401)
        status, task = self.call("POST", "/tasks", {"title": "Review pipeline"}, alice)
        self.assertEqual(status, 201)
        path = f'/tasks/{task["id"]}'
        self.assertEqual(self.call("DELETE", path, token=bob)[0], 404)
        self.assertEqual(self.call("PUT", path, {"done": True}, alice)[1]["done"], True)
        self.assertEqual(len(self.call("GET", "/tasks", token=alice)[1]["tasks"]), 1)
        self.assertEqual(self.call("DELETE", path, token=alice)[0], 200)
        self.assertEqual(self.call("GET", "/health")[0], 200)

    def test_expired_and_tampered_tokens(self):
        self.assertIsNone(server.user_from_token("Bearer " + server.token_for(1, 1)))
        self.assertIsNone(server.user_from_token("Bearer " + server.token_for(1) + "x"))


if __name__ == "__main__":
    unittest.main()
