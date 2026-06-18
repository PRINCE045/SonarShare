from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Tuple

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2

from config import crypto_config
from logging_utils import get_logger


logger = get_logger(__name__)


@dataclass
class EncryptedPayload:
    """
    Container for encrypted payload metadata and ciphertext.
    """

    salt: bytes
    iv: bytes
    ciphertext: bytes

    def serialize_compact(self) -> bytes:
        """
        Serialize as binary blob: salt || iv || ciphertext.
        """
        return self.salt + self.iv + self.ciphertext

    @classmethod
    def deserialize_compact(cls, blob: bytes) -> "EncryptedPayload":
        sl = crypto_config.salt_length_bytes
        ivl = crypto_config.iv_length_bytes
        if len(blob) < sl + ivl + AES.block_size:
            raise ValueError("Encrypted blob too small")
        salt = blob[:sl]
        iv = blob[sl : sl + ivl]
        ciphertext = blob[sl + ivl :]
        return cls(salt=salt, iv=iv, ciphertext=ciphertext)

    def to_header_fields(self) -> Tuple[str, str]:
        """
        Return (salt_b64, iv_b64) for use in packet headers.
        """
        return base64.b64encode(self.salt).decode("ascii"), base64.b64encode(
            self.iv
        ).decode("ascii")


def _derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("Password must not be empty")
    key = PBKDF2(
        password.encode("utf-8"),
        salt,
        dkLen=crypto_config.key_length_bits // 8,
        count=crypto_config.pbkdf2_iterations,
    )
    return key


def encrypt_payload(password: str, plaintext: bytes) -> EncryptedPayload:
    """
    Encrypt arbitrary bytes with AES-256-CBC using password-derived key.
    """
    salt = os.urandom(crypto_config.salt_length_bytes)
    key = _derive_key(password, salt)
    iv = os.urandom(crypto_config.iv_length_bytes)
    cipher = AES.new(key, AES.MODE_CBC, iv)

    pad_len = AES.block_size - (len(plaintext) % AES.block_size)
    padded = plaintext + bytes([pad_len] * pad_len)

    ciphertext = cipher.encrypt(padded)
    logger.debug("Encrypted payload of %d bytes", len(plaintext))
    return EncryptedPayload(salt=salt, iv=iv, ciphertext=ciphertext)


def decrypt_payload(password: str, encrypted: EncryptedPayload) -> bytes:
    """
    Decrypt bytes previously produced by encrypt_payload.
    """
    key = _derive_key(password, encrypted.salt)
    cipher = AES.new(key, AES.MODE_CBC, encrypted.iv)
    padded = cipher.decrypt(encrypted.ciphertext)
    if not padded:
        raise ValueError("Decryption produced empty result")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > AES.block_size or pad_len > len(padded):
        raise ValueError("Invalid padding")
    plaintext = padded[:-pad_len]
    logger.debug("Decrypted payload to %d bytes", len(plaintext))
    return plaintext


def encode_base64_for_sonar(raw: bytes) -> str:
    """
    Encode bytes into a restricted character set compatible with the FSK alphabet.

    Standard base64 uses '+', '/', and '='. We remap them into a set that fits
    the Sonar alphabet while remaining reversible:

    '+' -> '-'
    '/' -> ':'
    '=' -> '_'
    """
    b64 = base64.b64encode(raw).decode("ascii")
    return (
        b64.replace("+", "-")
        .replace("/", ":")
        .replace("=", "_")
    )


def decode_base64_from_sonar(text: str) -> bytes:
    """
    Reverse of encode_base64_for_sonar.
    """
    norm = text.replace("-", "+").replace(":", "/").replace("_", "=")
    return base64.b64decode(norm.encode("ascii"))

