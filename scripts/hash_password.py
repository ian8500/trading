from __future__ import annotations

from getpass import getpass

from argon2 import PasswordHasher


def main() -> int:
    first = getpass("New dashboard administrator password: ")
    second = getpass("Confirm password: ")
    if len(first) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    if first != second:
        raise SystemExit("Passwords do not match")
    print(PasswordHasher().hash(first))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
