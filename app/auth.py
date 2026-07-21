"""Hash de senha de mão única (PBKDF2-HMAC-SHA256, biblioteca padrão do Python).

Multiplataforma (Windows/macOS) e sem dependências externas. A senha NUNCA é
armazenada em texto puro — guardamos apenas o salt e o hash derivado.
"""

import hashlib
import hmac
import secrets

_ALGORITHM = "sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(password: str) -> tuple[str, str]:
    """Gera (salt_hex, hash_hex) para a senha informada."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, _ITERATIONS)
    return salt.hex(), derived.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Verifica a senha comparando o hash de forma resistente a timing attacks."""
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, _ITERATIONS)
    return hmac.compare_digest(derived.hex(), hash_hex)
