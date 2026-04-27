"""Envelope encryption for stored OAuth tokens.

We store GitHub install tokens, Slack OAuth tokens, etc. in
connections.credentials_encrypted (BYTEA). Encryption uses AES-GCM with a
master key from CREDENTIAL_ENCRYPTION_KEY (32-byte hex). Each ciphertext
includes its own random nonce so two encryptions of the same plaintext yield
different ciphertexts.

Format on disk:
  [12-byte nonce][AES-GCM ciphertext including 16-byte tag]
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


def _master_key() -> bytes:
    settings = get_settings()
    key_hex = settings.credential_encryption_key.strip()
    if len(key_hex) != 64:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY must be 32 bytes hex (64 chars). "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return bytes.fromhex(key_hex)


def encrypt(plaintext: bytes | str) -> bytes:
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    aes = AESGCM(_master_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct


def decrypt(blob: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(_master_key())
    return aes.decrypt(nonce, ct, associated_data=None)


def decrypt_str(blob: bytes) -> str:
    return decrypt(blob).decode()
