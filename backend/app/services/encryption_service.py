"""Fernet symmetric encryption for credential storage."""
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class EncryptionService:
    def __init__(self) -> None:
        key = settings.ENCRYPTION_KEY
        if key:
            self._fernet = Fernet(key.encode())
        else:
            self._fernet = None
            log.warning("encryption.no_key_configured")

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        if self._fernet is None:
            return plaintext  # passthrough in dev when no key set
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        if self._fernet is None:
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            log.error("encryption.invalid_token")
            return ""
