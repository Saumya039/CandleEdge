#!/usr/bin/env python3
"""Create the values for the web login. Run on YOUR machine or the server; nothing is sent anywhere.

  python scripts/hash_password.py            # prompts for a password (hidden)

Prints AUTH_PASSWORD_HASH and a fresh random AUTH_SECRET to paste into your server's .env.prod. The password
itself is never stored. Use a long, unique password (12+ characters)."""
import getpass
import hashlib
import secrets
import sys

ITERATIONS = 310_000

pw = getpass.getpass("Choose a login password: ")
if len(pw) < 12:
    sys.exit("Use at least 12 characters.")
if getpass.getpass("Repeat it: ") != pw:
    sys.exit("Passwords differ.")
salt = secrets.token_bytes(16)
dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITERATIONS)
print(f"AUTH_PASSWORD_HASH='pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}'")
print(f"AUTH_SECRET={secrets.token_hex(32)}")
