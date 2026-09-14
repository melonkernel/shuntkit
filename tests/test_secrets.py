from __future__ import annotations

from pathlib import Path

import pytest

from shuntkit.config import Config
from shuntkit.delegate import bulk_read
from shuntkit.secrets import find_secrets, secret_reason
from shuntkit.transports import Answer, TransportError, Usage


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        "prod.env",
        "server.pem",
        "id_rsa",
        "id_ed25519.pub",
        "credentials",
        "credentials.json",
        "secrets.yaml",
        "service-account-prod.json",
        "terraform.tfstate",
        ".npmrc",
    ],
)
def test_secret_names(tmp_path: Path, name: str):
    p = tmp_path / name
    p.write_text("x")
    assert secret_reason(p) is not None


@pytest.mark.parametrize(
    "name", ["main.py", "README.md", "env.py", "environment.ts", "keys_test.py", "package.json"]
)
def test_normal_names(tmp_path: Path, name: str):
    p = tmp_path / name
    p.write_text("x")
    assert secret_reason(p) is None


def test_secret_directories(tmp_path: Path):
    d = tmp_path / ".ssh"
    d.mkdir()
    p = d / "config"
    p.write_text("Host x")
    assert ".ssh" in secret_reason(p)


def test_pem_content_sniff(tmp_path: Path):
    p = tmp_path / "notes.txt"
    p.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n")
    assert "PEM" in secret_reason(p)


def test_bulk_read_refuses_secrets(tmp_path: Path, state_dir: Path):
    env = tmp_path / ".env"
    env.write_text("TOKEN=abc\n")
    ok = tmp_path / "app.py"
    ok.write_text("x = 1\n")

    class T:
        name = "t"

        def check(self):
            return []

        def invoke(self, s, m):
            raise AssertionError("must not be called")

    with pytest.raises(TransportError, match="likely secrets") as exc:
        bulk_read(T(), Config(state_dir=state_dir), [ok, env], "q")
    assert ".env" in str(exc.value)
    assert "SHUNTKIT_SECRET_GUARD=off" in str(exc.value)


def test_guard_can_be_disabled(tmp_path: Path, state_dir: Path):
    env = tmp_path / ".env"
    env.write_text("TOKEN=abc\n")

    class T:
        name = "t"

        def check(self):
            return []

        def invoke(self, s, m):
            return Answer(text="- ok", usage=Usage())

    result = bulk_read(T(), Config(state_dir=state_dir, secret_guard=False), [env], "q")
    assert result.answer.text == "- ok"


def test_find_secrets_lists_all(tmp_path: Path):
    a = tmp_path / ".env"
    b = tmp_path / "k.pem"
    c = tmp_path / "x.py"
    for f in (a, b, c):
        f.write_text("x")
    assert len(find_secrets([a, b, c])) == 2
