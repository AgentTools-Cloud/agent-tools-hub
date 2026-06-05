#!/usr/bin/env python3
"""Generate the secrets agent-tools-hub needs in .env.

  FERNET_KEY   — master key encrypting sellers' upstream auth secrets at rest
  ADMIN_TOKEN  — bearer token for the approval/admin API

Run once, paste the values into .env (chmod 600), and DO NOT COMMIT.
"""

import secrets

from cryptography.fernet import Fernet

print(f"FERNET_KEY={Fernet.generate_key().decode()}")
print(f"ADMIN_TOKEN={secrets.token_urlsafe(32)}")
