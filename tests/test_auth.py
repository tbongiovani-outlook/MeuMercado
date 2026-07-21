"""Testes de hash/verificação de senha (auth)."""

from app import auth


def test_hash_gera_salt_e_hash_distintos():
    salt, hashed = auth.hash_password("minha-senha")
    assert salt and hashed
    assert salt != hashed
    # Dois hashes da mesma senha usam salts diferentes (aleatórios).
    salt2, hashed2 = auth.hash_password("minha-senha")
    assert salt != salt2
    assert hashed != hashed2


def test_verify_password_correta():
    salt, hashed = auth.hash_password("segredo123")
    assert auth.verify_password("segredo123", salt, hashed) is True


def test_verify_password_incorreta():
    salt, hashed = auth.hash_password("segredo123")
    assert auth.verify_password("errada", salt, hashed) is False
