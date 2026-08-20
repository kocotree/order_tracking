import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PhoneProtector:
    def __init__(self, *, encryption_secret: bytes, digest_secret: bytes) -> None:
        self._cipher = AESGCM(hashlib.sha256(encryption_secret).digest())
        self._digest_secret = digest_secret

    def encrypt(self, phone: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, phone.encode(), b"order-tracking-phone-v1")
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def decrypt(self, encrypted_phone: str) -> str:
        payload = base64.urlsafe_b64decode(encrypted_phone.encode())
        return self._cipher.decrypt(
            payload[:12], payload[12:], b"order-tracking-phone-v1"
        ).decode()

    def digest(self, phone: str) -> str:
        return hmac.new(self._digest_secret, phone.encode(), hashlib.sha256).hexdigest()

    def mask(self, phone: str) -> str:
        return f"{phone[:3]}****{phone[-4:]}"
