"""Run locally with python3 generate_settings.py; keep the output private."""
import base64
import secrets

print('Paste these into your hosting environment settings, not GitHub files or chat:')
print('JWT_SIGNING_KEY=' + secrets.token_urlsafe(48))
print('STORAGE_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
