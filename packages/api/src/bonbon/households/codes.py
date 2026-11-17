"""Invite codes: generated here, stored only as a hash (docs/features/04-households.md)."""

import hashlib
import re
import secrets

# Without characters that are easy to mix up when typed off a phone: 0/O, 1/I/L.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# 31^8 ≈ 8.5e11 codes (about 40 bits). With 5 failed attempts per user and hour and a lifetime
# of 48 h, guessing one is out of reach, so a plain SHA-256 is enough (no salt, no bcrypt).
LENGTH = 8


def generate() -> str:
    """A new random code, formatted as XXXX-XXXX."""
    code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return f"{code[:4]}-{code[4:]}"


def normalize(code: str) -> str:
    """What the user typed, as generated: upper case, without dashes, spaces or other separators."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def code_hash(code: str) -> str:
    """The stored form of a code, as typed or as generated."""
    return hashlib.sha256(normalize(code).encode()).hexdigest()
