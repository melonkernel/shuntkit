"""Refuse to ship likely secrets to the worker model.

Delegation sends whole files off the machine. Credentials, private keys and
environment files should never take that trip by accident. This guard is
name-based plus a cheap content sniff for PEM private keys. It is a guard
rail, not a scanner: it will not catch an API key pasted into ``config.py``.

Disable with ``SHUNTKIT_SECRET_GUARD=off``.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

SECRET_NAME_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    "*.asc",
    "*.gpg",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    "_netrc",
    ".npmrc",
    ".pypirc",
    ".htpasswd",
    ".git-credentials",
    "credentials",
    "credentials.*",
    "secrets.*",
    "*.secret",
    "*.secrets",
    "service-account*.json",
    "*.tfvars",
    "*.tfstate",
    "*.tfstate.*",
)

SECRET_DIR_NAMES: frozenset[str] = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker"})

_PEM_MARKER = b"PRIVATE KEY-----"
_SNIFF_BYTES = 8192


def secret_reason(path: Path) -> str | None:
    """Return why ``path`` looks like a secret, or ``None`` if it looks fine."""
    name = path.name
    lower = name.lower()
    for pattern in SECRET_NAME_PATTERNS:
        if fnmatch.fnmatchcase(lower, pattern):
            return f"{path}: name matches secret pattern '{pattern}'"
    for part in path.parts[:-1]:
        if part.lower() in SECRET_DIR_NAMES:
            return f"{path}: inside a '{part}' directory"
    try:
        with path.open("rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError:
        return None
    if _PEM_MARKER in head and b"-----BEGIN" in head:
        return f"{path}: contains a PEM private key block"
    return None


def find_secrets(paths: list[Path]) -> list[str]:
    reasons = []
    for p in paths:
        reason = secret_reason(p)
        if reason:
            reasons.append(reason)
    return reasons
