"""Account and tenant checks use disposable data and never call a real model."""

import http.cookiejar
import json
import sqlite3
import threading
import time
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from workbench.accounts import (
    COOKIE_NAME,
    AccountError,
    Accounts,
    password_matches,
    validate_password,
)
from workbench.supervisor import AccountPlatform, Handler

PASSWORD = "Engineering-test-password-42"


@pytest.mark.parametrize("password", ["123456", "abcdef", "a1_b-6", "a" * 128])
def test_password_minimum_accepts_six_characters(password):
    assert validate_password(password) == password


@pytest.mark.parametrize("password", ["12345", "", None, 123456, "a" * 129])
def test_password_length_rejects_outside_supported_range(password):
    with pytest.raises(AccountError, match="6 到 128"):
        validate_password(password)


def test_six_character_passwords_support_all_account_operations(tmp_path):
    store = Accounts(tmp_path)
    store.create(
        {"username": "admin", "password": "123456", "setup_token": store.setup_path.read_text()},
        setup=True,
    )
    assert store.login({"username": "admin", "password": "123456"}, "fixture")
    member = store.create({"username": "member", "password": "123456"})
    store.change_password(member["id"], "123456", "654321")
    assert store.login({"username": "member", "password": "654321"}, "fixture")
    store.update_user(member["id"], {"password": "112233"})
    assert store.login({"username": "member", "password": "112233"}, "fixture")


@pytest.fixture
def accounts(tmp_path):
    store = Accounts(tmp_path)
    store.create(
        {"username": "admin", "password": PASSWORD, "setup_token": store.setup_path.read_text()},
        setup=True,
    )
    return store


def test_bootstrap_requires_server_token_and_assigns_legacy_owner(tmp_path):
    store = Accounts(tmp_path)
    with pytest.raises(AccountError, match="初始化口令"):
        store.create(
            {"username": "intruder", "password": PASSWORD, "setup_token": "wrong"}, setup=True
        )
    with pytest.raises(AccountError, match="初始化管理员"):
        store.create({"username": "member", "password": PASSWORD})
    owner = store.create(
        {"username": "admin", "password": PASSWORD, "setup_token": store.setup_path.read_text()},
        setup=True,
    )
    assert owner["role"] == "admin" and owner["legacy_owner"]
    assert not store.setup_path.exists()
    assert not store.needs_setup()
    with pytest.raises(AccountError):
        store.create({"username": "second_admin", "password": PASSWORD}, setup=True)


def test_password_storage_unique_usernames_and_registration_switch(accounts):
    user = accounts.create({"username": "Researcher", "password": PASSWORD})
    assert user["role"] == "member" and not user["legacy_owner"]
    with sqlite3.connect(accounts.path) as db:
        encoded = db.execute(
            "SELECT password_hash FROM users WHERE id=?", (user["id"],)
        ).fetchone()[0]
    assert encoded.startswith("scrypt$") and PASSWORD not in encoded
    assert password_matches(PASSWORD, encoded)
    assert not password_matches("incorrect", encoded)
    with pytest.raises(AccountError, match="已经注册"):
        accounts.create({"username": "researcher", "password": PASSWORD})
    accounts.set_registration(False)
    with pytest.raises(AccountError, match="关闭注册"):
        accounts.create({"username": "another", "password": PASSWORD})
    accounts.set_registration(True)
    assert accounts.create({"username": "another", "password": PASSWORD})


def test_session_logout_expiry_and_password_reset(accounts):
    user = accounts.create({"username": "member", "password": PASSWORD})
    _user, token = accounts.login({"username": "MEMBER", "password": PASSWORD}, "fixture")
    assert accounts.session(token)["user"]["id"] == user["id"]
    assert Accounts(accounts.directory).session(token)
    accounts.logout(token)
    assert accounts.session(token) is None
    _user, token = accounts.login({"username": "member", "password": PASSWORD}, "fixture")
    with accounts.connection() as db:
        db.execute("UPDATE sessions SET expires_at=0")
    assert accounts.session(token) is None
    _user, token = accounts.login({"username": "member", "password": PASSWORD}, "fixture")
    accounts.change_password(user["id"], PASSWORD, "Replacement-password-43")
    assert accounts.session(token) is None
    assert accounts.login({"username": "member", "password": "Replacement-password-43"}, "fixture")


def test_disabling_revokes_sessions_and_last_admin_is_protected(accounts):
    admin = accounts.list_users()[0]
    with pytest.raises(AccountError, match="至少需要"):
        accounts.update_user(admin["id"], {"active": False})
    with pytest.raises(AccountError, match="管理员角色"):
        accounts.update_user(admin["id"], {"role": "member"})
    member = accounts.create({"username": "member", "password": PASSWORD})
    _, token = accounts.login({"username": "member", "password": PASSWORD}, "fixture")
    accounts.update_user(member["id"], {"active": False})
    assert accounts.session(token) is None
    with pytest.raises(AccountError):
        accounts.login({"username": "member", "password": PASSWORD}, "fixture")


def test_failed_login_rate_limit_is_persistent(accounts):
    for _ in range(10):
        with pytest.raises(AccountError) as failure:
            accounts.login({"username": "unknown", "password": "wrong"}, "fixture")
        assert failure.value.status == 401
    restored = Accounts(accounts.directory)
    with pytest.raises(AccountError) as failure:
        restored.login({"username": "unknown", "password": "wrong"}, "fixture")
    assert failure.value.status == 429


class Browser:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.csrf = ""
        self.user_id = ""

    def request(self, path, payload=None, *, method=None, headers=None, csrf=True):
        headers = {"Content-Type": "application/json", **(headers or {})}
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
            headers["X-AutoResearch-Account"] = self.user_id
        req = Request(
            self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers=headers,
        )
        try:
            response = self.opener.open(req, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            value = (
                json.loads(body)
                if "application/json" in response.headers.get("Content-Type", "")
                else body
            )
            return response.status, value, response.headers

    def login(self, username):
        code, value, headers = self.request(
            "/api/auth/login", {"username": username, "password": PASSWORD}
        )
        assert code == 200, value
        cookie = headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
        assert COOKIE_NAME in cookie
        _, session, _ = self.request("/api/auth/session")
        self.csrf, self.user_id = session["csrf_token"], session["user"]["id"]
        return value["user"]


@pytest.fixture
def platform(tmp_path):
    app = AccountPlatform(tmp_path, tmp_path / "assets/output/workbench")
    app.accounts.create(
        {
            "username": "admin",
            "password": PASSWORD,
            "setup_token": app.accounts.setup_path.read_text(),
        },
        setup=True,
    )
    for name in ("alice", "bob"):
        app.accounts.create({"username": name, "password": PASSWORD})
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, platform=app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, server.server_port
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(5)


def wait_ready(browser):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        code, state, _ = browser.request("/api/service")
        if code == 200 and state["connected"]:
            return
        time.sleep(0.1)
    raise AssertionError("Account worker did not become ready")


@pytest.mark.parametrize(
    "path",
    [
        "/api/pipelines",
        "/auto-design/api/tasks",
        "/auto-writing/api/writings",
        "/auto-search/api/runs",
        "/auto-table/api/projects",
        "/auto-figure/api/projects",
        "/api/service/log",
        "/api/admin/users",
    ],
)
def test_anonymous_api_requests_require_login(platform, path):
    _app, port = platform
    browser = Browser(port)
    assert browser.request(path)[0] == 401
    assert browser.request("/login.html")[0] == 200


def test_authenticated_gateway_enforces_csrf_and_admin_permissions(platform):
    app, port = platform
    browser = Browser(port)
    browser.login("alice")
    assert browser.request("/api/admin/users")[0] == 403
    assert browser.request("/accounts.html")[0] == 403
    assert browser.request("/api/auth/logout", method="POST", csrf=False)[0] == 403
    assert (
        browser.request(
            "/api/auth/logout", method="POST", headers={"Origin": "https://other.example"}
        )[0]
        == 403
    )
    assert (
        browser.request("/api/service/restart", {"settings": {"CODEX_CLI": "/tmp/untrusted"}})[0]
        == 403
    )
    assert browser.request("/auto-search/data/ideas.json")[0] == 404
    assert browser.request("/auto-search/assets/%252e%252e/data/ideas.json")[0] == 400
    assert browser.request("/api/runtime/prepare-restart", {})[0] == 403
    assert not app.services
    assert browser.request("/api/auth/logout", method="POST")[0] == 200
    assert browser.request("/api/pipelines")[0] == 401


def test_real_workers_isolate_projects_files_and_imports(platform):
    app, port = platform
    alice, bob = Browser(port), Browser(port)
    alice_user, bob_user = alice.login("alice"), bob.login("bob")
    wait_ready(alice)
    wait_ready(bob)
    assert app.services[alice_user["id"]].process.pid != app.services[bob_user["id"]].process.pid
    for path, key in (
        ("/auto-search/api/runs", "runs"),
        ("/auto-design/api/tasks", "tasks"),
        ("/auto-writing/api/writings", "writings"),
        ("/auto-table/api/projects", "projects"),
        ("/auto-figure/api/projects", "projects"),
        ("/api/pipelines", "pipelines"),
    ):
        assert alice.request(path)[1][key] == []
        assert bob.request(path)[1][key] == []
    code, task, _ = alice.request(
        "/auto-design/api/tasks",
        {
            "title": "Alice private project",
            "idea": "Motivation: engineering fixture\nContribution: fixture",
            "scope": "design_only",
        },
    )
    assert code == 201, task
    assert Path(task["run_dir"]).is_relative_to(app.services[alice_user["id"]].workspace)
    task_path = f"/auto-design/api/tasks/{task['id']}"
    assert bob.request("/auto-design/api/tasks")[1]["tasks"] == []
    assert bob.request(task_path)[0] == 400
    assert bob.request(task_path + "/files/idea.md")[0] == 400
    assert alice.request(task_path + "/files/idea.md")[0] == 200
    report = Path(task["run_dir"]) / "reports/index.html"
    report.parent.mkdir(exist_ok=True)
    report.write_text("<html><body>Engineering report</body></html>")
    artifact = alice.request(task_path + "/files/reports/index.html")
    assert artifact[2]["Content-Security-Policy"] == "sandbox allow-scripts allow-downloads"
    assert b"/account.js" not in artifact[1]
    assert alice.request(task_path + "/files/../other.txt")[0] == 400
    assert (
        bob.request(
            "/auto-design/api/tasks/import",
            {"run_dir": task["run_dir"], "workspace": task["workspace"]},
        )[0]
        == 400
    )
    assert (
        bob.request("/auto-design/api/tasks", {"idea": "Fixture", "workspace": str(app.workspace)})[
            0
        ]
        == 400
    )
    assert (
        bob.request("/api/pipelines", {"start_stage": "design", "source_id": task["id"]})[0] == 400
    )
    log = alice.request("/api/service/log")[1]
    assert str(app.services[bob_user["id"]].workspace).encode() not in log
    service = app.services[alice_user["id"]]
    direct = Browser(service.port)
    assert direct.request("/api/runtime")[0] == 403
    assert alice.request("/auto-design/")[1].count(b"/account.js") == 1
    page = alice.request("/auto-design/")
    head = alice.request("/auto-design/", method="HEAD")
    assert head[0] == 200 and head[2]["Content-Length"] == page[2]["Content-Length"]
    deleted = alice.request(
        task_path, {"passphrase": "DEL"}, method="DELETE", headers={"Origin": alice.base}
    )
    assert deleted[0] == 200, deleted[1]
    assert alice.request("/auto-design/api/tasks")[1]["tasks"] == []


def test_admin_controls_and_legacy_project_namespace(platform):
    app, port = platform
    from auto_design.orchestration import TaskManager

    previous = TaskManager(app.data_dir / "auto_design").create(
        "Existing research",
        "Motivation: existing engineering fixture",
        str(app.workspace),
        "design_only",
    )
    original_idea = (Path(previous["run_dir"]) / "idea.md").read_bytes()
    admin = Browser(port)
    owner = admin.login("admin")
    wait_ready(admin)
    assert app.services[owner["id"]].workspace == app.workspace
    assert app.services[owner["id"]].data_dir == app.data_dir
    assert admin.request("/auto-design/api/tasks")[1]["tasks"][0]["id"] == previous["id"]
    assert (Path(previous["run_dir"]) / "idea.md").read_bytes() == original_idea
    assert admin.request("/auto-design/")[0] == 200
    users = admin.request("/api/admin/users")[1]["users"]
    member = next(user for user in users if user["username"] == "alice")
    alice = Browser(port)
    alice.login("alice")
    assert admin.request("/api/admin/settings", {"registration_open": False})[0] == 200
    assert (
        Browser(port).request("/api/auth/register", {"username": "new_user", "password": PASSWORD})[
            0
        ]
        == 403
    )
    assert admin.request(f"/api/admin/users/{member['id']}", {"active": False})[0] == 200
    assert alice.request("/api/pipelines")[0] == 401
    assert admin.request(f"/api/admin/users/{owner['id']}", {"active": False})[0] == 409
    assert admin.request("/accounts.html")[0] == 200


def test_browser_registration_stays_a_member_and_cookie_can_require_https(platform):
    app, port = platform
    browser = Browser(port)
    code, data, _headers = browser.request(
        "/api/auth/register",
        {
            "username": "new_member",
            "password": PASSWORD,
            "role": "admin",
            "legacy_owner": True,
        },
    )
    assert code == 201
    assert data["user"]["role"] == "member" and not data["user"]["legacy_owner"]
    assert browser.request("/api/admin/users")[0] == 403
    app.secure_cookies = True
    code, _data, headers = Browser(port).request(
        "/api/auth/login", {"username": "bob", "password": PASSWORD}
    )
    assert code == 200 and "Secure" in headers["Set-Cookie"]


def test_disabling_live_worker_preserves_projects_and_reactivation(platform):
    app, port = platform
    admin, alice = Browser(port), Browser(port)
    admin.login("admin")
    member = alice.login("alice")
    wait_ready(alice)
    code, task, _ = alice.request(
        "/auto-design/api/tasks",
        {
            "title": "Retained project",
            "idea": "Motivation: engineering fixture",
            "scope": "design_only",
        },
    )
    assert code == 201
    old_service = app.services[member["id"]]
    assert admin.request(f"/api/admin/users/{member['id']}", {"active": False})[0] == 200
    assert alice.request("/auto-design/api/tasks")[0] == 401
    deadline = time.monotonic() + 15
    while old_service.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert old_service.process.poll() is not None
    assert admin.request(f"/api/admin/users/{member['id']}", {"active": True})[0] == 200
    alice.login("alice")
    wait_ready(alice)
    assert app.services[member["id"]].process.pid != old_service.process.pid
    assert alice.request("/auto-design/api/tasks")[1]["tasks"][0]["id"] == task["id"]
    assert (Path(task["run_dir"]) / "idea.md").is_file()
