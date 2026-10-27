#!/usr/bin/env python3
"""Mint a long-lived Sign House JWT for MCP (Cursor / Loom Connections).

Uses MONGO_URI + JWT_SECRET_KEY from backend/.env. Does not change global JWT_ACCESS_TOKEN_HOURS.

  cd backend
  PYTHONPATH=. python scripts/mint_mcp_token.py --email you@example.com
  PYTHONPATH=. python scripts/mint_mcp_token.py --email mcp@local --create-user --role user

Output: access_token (paste into Cursor mcp.json or Loom wa connection). Do not commit.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or (BACKEND / '.env')
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def main() -> int:
    parser = argparse.ArgumentParser(description='Mint long-lived MCP JWT')
    parser.add_argument('--email', help='User email (login identity)')
    parser.add_argument('--username', help='Username (alternative lookup)')
    parser.add_argument('--hours', type=int, default=None, help='Token lifetime in hours')
    parser.add_argument(
        '--create-user',
        action='store_true',
        help='Create user if missing (requires --email; password printed once)',
    )
    parser.add_argument('--role', default='user', choices=('user', 'manager', 'admin'))
    parser.add_argument(
        '--env-file',
        help='Load env from this path (e.g. Coolify .env with production JWT_SECRET_KEY + MONGO_URI)',
    )
    args = parser.parse_args()

    if not args.email and not args.username:
        parser.error('Provide --email or --username')

    env_path = Path(args.env_file).expanduser() if args.env_file else None
    _load_dotenv(env_path)
    hours = args.hours
    if hours is None:
        hours = int(os.environ.get('MCP_SERVICE_TOKEN_HOURS', '87600'))  # ~10 years

    from app import create_app, mongo
    from app.models import create_user_doc, user_to_dict
    from flask_jwt_extended import create_access_token

    import logging

    logging.disable(logging.CRITICAL)
    os.environ.setdefault('SIGNHOUSE_START_SCHEDULERS', '0')
    app = create_app(os.environ.get('FLASK_CONFIG', 'development'))
    app.logger.disabled = True
    with app.app_context():
        query = {}
        if args.email:
            query = {'$or': [{'email': args.email}, {'username': args.email}]}
        elif args.username:
            query = {'username': args.username}

        user = mongo.db.users.find_one(query)
        new_password = None
        if not user and args.create_user and args.email:
            uname = args.email.split('@')[0].replace('.', '_')[:32]
            new_password = secrets.token_urlsafe(16)
            doc = create_user_doc(uname, args.email, new_password, role=args.role)
            rid = mongo.db.users.insert_one(doc).inserted_id
            user = mongo.db.users.find_one({'_id': rid})
            print(f'Created user username={uname} email={args.email} role={args.role}', file=sys.stderr)
            print(f'One-time password (store in 1Password): {new_password}', file=sys.stderr)

        if not user:
            print('User not found. Use --create-user with --email or pick an existing account.', file=sys.stderr)
            return 1

        if not user.get('is_active', True):
            print('User is deactivated.', file=sys.stderr)
            return 1

        token = create_access_token(
            identity=str(user['_id']),
            expires_delta=timedelta(hours=hours),
        )
        u = user_to_dict(user)
        print(f"# MCP long-lived JWT (~{hours}h) for {u.get('email')} ({u.get('role')})")
        print(f"# Expires per JWT exp claim — verify with: curl -H 'Authorization: Bearer …' …/api/auth/me")
        print(token)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
