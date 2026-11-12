"""SQLite accounts, password hashes and revocable browser sessions."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SESSION_SECONDS = 7 * 24 * 60 * 60
COOKIE_NAME = "autoresearch_session"
PASSWORD_WORKERS = threading.BoundedSemaphore(2)


class AccountError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    with PASSWORD_WORKERS:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=32768,
            r=8,
            p=3,
            dklen=64,
            maxmem=64 * 1024 * 1024,
        )
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, _digest = encoded.split("$")
        if algorithm != "scrypt":
            return False
        candidate = password_hash(password, base64.b64decode(salt, validate=True))
        return hmac.compare_digest(candidate, encoded)
    except (ValueError, TypeError):
        return False


def validate_password(value: object) -> str:
    if not isinstance(value, str) or not 6 <= len(value) <= 128:
        raise AccountError("密码长度需要为 6 到 128 个字符。")
    return value


def validate_username(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,31}", value):
        raise AccountError(
            "用户名需为 3 到 32 位字母、数字、下划线、点或连字符，并以字母或数字开头。"
        )
    return value


def public_user(row) -> dict:
    return {
        key: row[key]
        for key in (
            "id",
            "username",
            "display_name",
            "role",
            "active",
            "legacy_owner",
            "created_at",
            "last_login",
        )
    }


class Accounts:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "accounts.sqlite3"
        self.setup_path = self.directory / ".account-setup-token"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'member')),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    legacy_owner INTEGER NOT NULL DEFAULT 0 CHECK(legacy_owner IN (0, 1)),
                    created_at REAL NOT NULL,
                    last_login REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_legacy_owner
                    ON users(legacy_owner) WHERE legacy_owner = 1;
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES ('registration_open', 'true');
                CREATE TABLE IF NOT EXISTS login_attempts (
                    key TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start REAL NOT NULL
                );
                PRAGMA user_version=1;
            """)
        self.path.chmod(0o600)
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))
        if self.needs_setup():
            try:
                descriptor = os.open(self.setup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "w") as output:
                    output.write(secrets.token_urlsafe(32))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def needs_setup(self) -> bool:
        with self.connection() as db:
            return db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone() is None

    def registration_open(self) -> bool:
        with self.connection() as db:
            return (
                db.execute("SELECT value FROM settings WHERE key='registration_open'").fetchone()[0]
                == "true"
            )

    def create(self, payload: dict, *, setup: bool = False) -> dict:
        username = validate_username(payload.get("username"))
        password = validate_password(payload.get("password"))
        display = str(payload.get("display_name", "")).strip() or username
        if len(display) > 60:
            raise AccountError("显示名称最多 60 个字符。")
        encoded = password_hash(password)
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                has_admin = db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()
                if setup:
                    supplied = payload.get("setup_token")
                    expected = self.setup_path.read_text() if self.setup_path.is_file() else ""
                    if (
                        has_admin
                        or not isinstance(supplied, str)
                        or not expected
                        or not hmac.compare_digest(supplied, expected)
                    ):
                        raise AccountError("初始化口令无效，或管理员已经创建。", 403)
                elif not has_admin:
                    raise AccountError("请先由平台维护者初始化管理员。", 403)
                elif (
                    db.execute(
                        "SELECT value FROM settings WHERE key='registration_open'"
                    ).fetchone()[0]
                    != "true"
                ):
                    raise AccountError("管理员已关闭注册。", 403)
                user_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO users (id, username, username_key, display_name, password_hash, role, legacy_owner, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        username,
                        username.casefold(),
                        display,
                        encoded,
                        "admin" if setup else "member",
                        int(setup),
                        time.time(),
                    ),
                )
                user = public_user(
                    db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                )
        except sqlite3.IntegrityError as error:
            raise AccountError("这个用户名已经注册。", 409) from error
        if setup:
            self.setup_path.unlink(missing_ok=True)
        return user

    def login(self, payload: dict, client: str) -> tuple[dict, str]:
        username = payload.get("username", "")
        password = payload.get("password", "")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or len(username) > 128
            or len(password) > 128
        ):
            raise AccountError("用户名或密码错误。", 401)
        key = hashlib.sha256((client + "\0" + username.casefold()).encode()).hexdigest()
        now = time.time()
        # Reserve an attempt before hashing so concurrent requests share the same limit.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE window_start < ?", (now - 900,))
            row = db.execute("SELECT failures FROM login_attempts WHERE key=?", (key,)).fetchone()
            if row and row[0] >= 10:
                raise AccountError("登录尝试过于频繁，请 15 分钟后重试。", 429)
            db.execute(
                "INSERT INTO login_attempts VALUES (?, 1, ?) ON CONFLICT(key) DO UPDATE SET failures=failures+1",
                (key, now),
            )
            row = db.execute(
                "SELECT * FROM users WHERE username_key=?", (username.casefold(),)
            ).fetchone()
        matched = password_matches(password, row["password_hash"] if row else self.dummy_hash)
        if not row or not matched or not row["active"]:
            raise AccountError("用户名或密码错误，或账号已停用。", 401)
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Password resets and disabling an account invalidate in-flight logins too.
            current = db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not current["active"] or current["password_hash"] != row["password_hash"]:
                raise AccountError("账号状态已更新，请重新登录。", 401)
            db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute("UPDATE users SET last_login=? WHERE id=?", (now, row["id"]))
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    row["id"],
                    secrets.token_urlsafe(32),
                    now + SESSION_SECONDS,
                ),
            )
            user = public_user(
                db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            )
        return user, token

    def session(self, token: str) -> dict | None:
        if not token or len(token) > 128:
            return None
        with self.connection() as db:
            row = db.execute(
                "SELECT users.*, sessions.csrf_token FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires_at>? AND active=1",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
            return {"user": public_user(row), "csrf_token": row["csrf_token"]} if row else None

    def logout(self, token: str) -> None:
        with self.connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def change_password(self, user_id: str, current: object, replacement: object) -> None:
        replacement = validate_password(replacement)
        with self.connection() as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        if (
            not isinstance(current, str)
            or len(current) > 128
            or not password_matches(current, row[0])
        ):
            raise AccountError("当前密码错误。", 403)
        encoded = password_hash(replacement)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE users SET password_hash=? WHERE id=? AND password_hash=?",
                (encoded, user_id, row[0]),
            ).rowcount
            if not changed:
                raise AccountError("密码已更新，请重新登录。", 409)
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def list_users(self) -> list[dict]:
        with self.connection() as db:
            return [
                public_user(row) for row in db.execute("SELECT * FROM users ORDER BY created_at")
            ]

    def update_user(self, user_id: str, payload: dict) -> dict:
        encoded = (
            password_hash(validate_password(payload["password"])) if "password" in payload else None
        )
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise AccountError("账号不存在。", 404)
            active = payload.get("active", bool(row["active"]))
            role = payload.get("role", row["role"])
            if type(active) is not bool or role not in {"admin", "member"}:
                raise AccountError("账号状态或角色无效。")
            if row["legacy_owner"] and role != "admin":
                raise AccountError("现有项目的归属账号需要保留管理员角色。", 409)
            if row["role"] == "admin" and row["active"] and (role != "admin" or not active):
                count = db.execute(
                    "SELECT count(*) FROM users WHERE role='admin' AND active=1"
                ).fetchone()[0]
                if count <= 1:
                    raise AccountError("平台至少需要保留一个启用的管理员。", 409)
            db.execute(
                "UPDATE users SET role=?, active=?, password_hash=? WHERE id=?",
                (
                    role,
                    int(active),
                    encoded or row["password_hash"],
                    user_id,
                ),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def set_registration(self, opened: object) -> None:
        if type(opened) is not bool:
            raise AccountError("注册开关必须为布尔值。")
        with self.connection() as db:
            db.execute(
                "UPDATE settings SET value=? WHERE key='registration_open'",
                ("true" if opened else "false",),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoResearch 本机管理员账号恢复")
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / "assets/output/workbench")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    if not (args.data_dir / "accounts.sqlite3").is_file():
        parser.error("所选数据目录中没有账号数据库")
    accounts = Accounts(args.data_dir)
    user = next(
        (
            user
            for user in accounts.list_users()
            if user["username"].casefold() == args.username.casefold()
        ),
        None,
    )
    if user is None:
        parser.error("账号不存在")
    replacement = getpass.getpass("输入新密码（6 到 128 个字符） ")
    if replacement != getpass.getpass("再次输入新密码 "):
        parser.error("两次输入的密码不一致")
    try:
        accounts.update_user(user["id"], {"password": replacement})
    except AccountError as error:
        parser.error(str(error))
    print("密码已更新，该账号的现有登录会话已撤销。")


if __name__ == "__main__":
    main()
