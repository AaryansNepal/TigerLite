"""Mirror of the control plane's crypto so the runtime can decrypt stored
OAuth tokens locally (Slack bot token, etc.). The encryption key is shared
via env. In production we'd centralize this in the control plane but for
demo simplicity both services know how to decrypt.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _master_key() -> bytes:
    key_hex = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "00" * 32).strip()
    if len(key_hex) != 64:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be 32 bytes hex")
    return bytes.fromhex(key_hex)


def decrypt(blob: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(_master_key())
    return aes.decrypt(nonce, ct, associated_data=None)


def decrypt_str(blob: bytes) -> str:
    return decrypt(blob).decode()
