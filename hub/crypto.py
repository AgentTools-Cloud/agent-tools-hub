"""Encrypt sellers' upstream auth secrets at rest with a single master key.

Mirrors the facilitator's hot-wallet-key handling: the master FERNET_KEY lives
only in .env (chmod 600); ciphertext is stored in SQLite. A DB exfiltration
alone cannot reveal any seller's upstream API key.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, fernet_key: str):
        if not fernet_key:
            raise RuntimeError("FERNET_KEY is empty — run scripts/gen_keys.py")
        self._f = Fernet(fernet_key.encode())

    def encrypt(self, plaintext: str | None) -> str | None:
        if not plaintext:
            return None
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str | None) -> str | None:
        if not ciphertext:
            return None
        return self._f.decrypt(ciphertext.encode()).decode()
