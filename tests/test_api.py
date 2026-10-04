import json
import os
import tempfile
import threading
import unittest
import uuid
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

        cls.http = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.Handler,
        )

        cls.thread = threading.Thread(
            target=cls.http.serve_forever,
            daemon=True,
        )
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

        request = Request(
            self.base + path,
            json.dumps(data).encode() if data is not None else None,
            headers,
            method=method,
        )

        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error

        return response.status, json.load(response)

    def unique_username(self, prefix="user"):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def register_and_login(self, prefix="user"):
        username = self.unique_username(prefix)
        password = "a secure password"

        status, _ = self.call(
            "POST",
            "/register",
            {
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(status, 201)

        status, body = self.call(
            "POST",
            "/login",
            {
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(status, 200)

        return username, body["token"]

    # --------------------------------------------------
    # Health
    # --------------------------------------------------

    def test_health_endpoint(self):
        status, _ = self.call("GET", "/health")
        self.assertEqual(status, 200)

    # --------------------------------------------------
    # Authentication
    # --------------------------------------------------

    def test_register_user(self):
        username = self.unique_username("register")

        status, _ = self.call(
            "POST",
            "/register",
            {
                "username": username,
                "password": "a secure password",
            },
        )

        self.assertEqual(status, 201)

    def test_login_success(self):
        username = self.unique_username("login")
        password = "a secure password"

        self.call(
            "POST",
            "/register",
            {
                "username": username,
                "password": password,
            },
        )

        status, body = self.call(
            "POST",
            "/login",
            {
                "username": username,
                "password": password,
            },
        )

        self.assertEqual(status, 200)
        self.assertIn("token", body)

    def test_login_wrong_password(self):
        username = self.unique_username("wrongpassword")

        self.call(
            "POST",
            "/register",
            {
                "username": username,
                "password": "correct password",
            },
        )

        status, _ = self.call(
            "POST",
            "/login",
            {
                "username": username,
                "password": "wrong password",
            },
        )

        self.assertEqual(status, 401)

    def test_tasks_require_authentication(self):
        status, _ = self.call("GET", "/tasks")
        self.assertEqual(status, 401)

    def test_expired_token_rejected(self):
        token = server.token_for(1, 1)

        self.assertIsNone(
            server.user_from_token("Bearer " + token)
        )

    def test_tampered_token_rejected(self):
        token = server.token_for(1) + "x"

        self.assertIsNone(
            server.user_from_token("Bearer " + token)
        )

    # --------------------------------------------------
    # CRUD
    # --------------------------------------------------

    def test_create_task(self):
        _, token = self.register_and_login("create")

        status, task = self.call(
            "POST",
            "/tasks",
            {"title": "Review pipeline"},
            token,
        )

        self.assertEqual(status, 201)
        self.assertEqual(task["title"], "Review pipeline")

    def test_list_tasks(self):
        _, token = self.register_and_login("list")

        self.call(
            "POST",
            "/tasks",
            {"title": "Task one"},
            token,
        )

        status, body = self.call(
            "GET",
            "/tasks",
            token=token,
        )

        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["tasks"]), 1)

    def test_update_task(self):
        _, token = self.register_and_login("update")

        _, task = self.call(
            "POST",
            "/tasks",
            {"title": "Update me"},
            token,
        )

        status, updated = self.call(
            "PUT",
            f'/tasks/{task["id"]}',
            {"done": True},
            token,
        )

        self.assertEqual(status, 200)
        self.assertTrue(updated["done"])

    def test_delete_task(self):
        _, token = self.register_and_login("delete")

        _, task = self.call(
            "POST",
            "/tasks",
            {"title": "Delete me"},
            token,
        )

        status, _ = self.call(
            "DELETE",
            f'/tasks/{task["id"]}',
            token=token,
        )

        self.assertEqual(status, 200)

    def test_deleted_task_disappears(self):
        _, token = self.register_and_login("deleted")

        _, task = self.call(
            "POST",
            "/tasks",
            {"title": "Temporary task"},
            token,
        )

        self.call(
            "DELETE",
            f'/tasks/{task["id"]}',
            token=token,
        )

        status, body = self.call(
            "GET",
            "/tasks",
            token=token,
        )

        self.assertEqual(status, 200)

        ids = [item["id"] for item in body["tasks"]]

        self.assertNotIn(task["id"], ids)

    # --------------------------------------------------
    # User isolation / authorization
    # --------------------------------------------------

    def test_user_cannot_delete_another_users_task(self):
        _, alice_token = self.register_and_login("alice")
        _, bob_token = self.register_and_login("bob")

        _, task = self.call(
            "POST",
            "/tasks",
            {"title": "Alice private task"},
            alice_token,
        )

        status, _ = self.call(
            "DELETE",
            f'/tasks/{task["id"]}',
            token=bob_token,
        )

        self.assertEqual(status, 404)

    def test_users_only_see_their_own_tasks(self):
        _, alice_token = self.register_and_login("aliceview")
        _, bob_token = self.register_and_login("bobview")

        self.call(
            "POST",
            "/tasks",
            {"title": "Alice secret task"},
            alice_token,
        )

        status, body = self.call(
            "GET",
            "/tasks",
            token=bob_token,
        )

        self.assertEqual(status, 200)

        titles = [task["title"] for task in body["tasks"]]

        self.assertNotIn("Alice secret task", titles)


if __name__ == "__main__":
    unittest.main()
