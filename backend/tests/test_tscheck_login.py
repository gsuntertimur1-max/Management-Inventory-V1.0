"""Backend coverage for the login acceptance criteria.

Covers: successful login for all three seeded roles, rejection of unknown/wrong
credentials, username case-insensitivity + password case-sensitivity, and that
unauthenticated requests to protected endpoints are denied (401).
"""
import httpx
import pytest

from tests.conftest import api_url


SEEDED = [
    ("admin", "admin123", "admin", "Administrator Gudang"),
    ("operator1", "operator123", "operator", "Operator Gudang"),
    ("viewer1", "viewer123", "viewer", "Pemantau Stok"),
]


@pytest.mark.parametrize("username,password,role,_label", SEEDED)
def test_login_success_seeded_accounts(username, password, role, _label):
    with httpx.Client(timeout=30.0) as c:
        resp = c.post(api_url("/auth/login"), json={"username": username, "password": password})
        assert resp.status_code == 200, f"{username} login failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["username"] == username
        assert body["role"] == role
        assert "gp_session" in resp.cookies, "gp_session cookie was not set on successful login"

        # /auth/me should reflect the session cookie
        me = c.get(api_url("/auth/me"), cookies=resp.cookies)
        assert me.status_code == 200
        me_body = me.json()
        assert me_body is not None
        assert me_body["username"] == username


def test_login_rejects_unknown_account():
    with httpx.Client(timeout=30.0) as c:
        resp = c.post(api_url("/auth/login"), json={"username": "user@email.com", "password": "whatever"})
        assert resp.status_code == 401
        assert "Username atau password salah" in resp.text
        assert "gp_session" not in resp.cookies


def test_login_rejects_wrong_password():
    with httpx.Client(timeout=30.0) as c:
        resp = c.post(api_url("/auth/login"), json={"username": "admin", "password": "wrong-pass-123"})
        assert resp.status_code == 401
        assert "Username atau password salah" in resp.text
        assert "gp_session" not in resp.cookies


def test_username_case_insensitive_password_case_sensitive():
    with httpx.Client(timeout=30.0) as c:
        # Capitalised username still logs in
        ok = c.post(api_url("/auth/login"), json={"username": "Admin", "password": "admin123"})
        assert ok.status_code == 200, ok.text
        assert "gp_session" in ok.cookies

        # Wrongly-capitalised password is rejected
        bad = c.post(api_url("/auth/login"), json={"username": "admin", "password": "Admin123"})
        assert bad.status_code == 401, bad.text
        assert "gp_session" not in bad.cookies


def test_unauthenticated_requests_rejected():
    with httpx.Client(timeout=30.0) as c:
        for path in ("/products", "/suppliers", "/stats"):
            resp = c.get(api_url(path))
            assert resp.status_code == 401, f"{path} should require auth, got {resp.status_code}"
