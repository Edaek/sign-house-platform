#!/usr/bin/env python3
"""
WA-Bot → Sign House v3 data migration script.

Migrates MongoDB collections from the standalone wa-bot database
into sign-house-v3's unified database.

Usage:
    python migrate_wa_data.py \
        --source mongodb://localhost:27017/signhouse \
        --target mongodb://localhost:27017/signhouse_dev \
        [--dry-run] [--skip-media]
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

from pymongo import MongoClient


COLLECTION_MAP = {
    'projects':            'wa_projects',
    'records':             'wa_records',
    'poolimages':          'pool_images',
    'grouppendingimages':  'group_pending_images',
    'keywords':            'wa_keywords',
    'recordtemplates':     'wa_templates',
    'organizations':       'wa_organizations',
    'pendingphotos':       'wa_pending_photos',
}


def migrate_collection(src_db, dst_db, src_name, dst_name, dry_run=False):
    src_coll = src_db[src_name]
    dst_coll = dst_db[dst_name]
    docs = list(src_coll.find())
    count = len(docs)

    if count == 0:
        print(f'  {src_name} → {dst_name}: 0 documents (skip)')
        return 0

    if dry_run:
        print(f'  {src_name} → {dst_name}: {count} documents (dry-run, not written)')
        return count

    existing = dst_coll.count_documents({})
    if existing > 0:
        print(f'  {src_name} → {dst_name}: target already has {existing} docs, skipping (use --force to overwrite)')
        return 0

    dst_coll.insert_many(docs)
    print(f'  {src_name} → {dst_name}: {count} documents migrated')
    return count


def migrate_users(src_db, dst_db, dry_run=False):
    """Merge wa-bot users into v3 by email. Creates new users if not found."""
    src_users = list(src_db['users'].find())
    created = 0
    merged = 0

    for u in src_users:
        email = u.get('email', '')
        if not email:
            continue

        existing = dst_db['users'].find_one({'email': email})
        if existing:
            merged += 1
            if not dry_run:
                print(f'  User {email}: already exists in v3 (id={existing["_id"]})')
        else:
            if dry_run:
                print(f'  User {email}: would be created')
            else:
                role = u.get('role', 'user')
                role = {'pm': 'manager', 'readonly': 'user'}.get(role, role)
                new_user = {
                    'username': u.get('name', email.split('@')[0]),
                    'email': email,
                    'password_hash': u.get('passwordHash', ''),
                    'role': role,
                    'is_active': True,
                    'created_at': u.get('createdAt', datetime.utcnow()),
                    'updated_at': datetime.utcnow(),
                }
                dst_db['users'].insert_one(new_user)
                print(f'  User {email}: created in v3')
            created += 1

    print(f'  Users: {merged} merged, {created} created')
    return created + merged


def migrate_media(src_media_dir, dst_media_dir, dry_run=False):
    """Copy media files from wa-bot uploads to v3 uploads/wa-media."""
    if not os.path.isdir(src_media_dir):
        print(f'  Source media dir not found: {src_media_dir}')
        return 0

    os.makedirs(dst_media_dir, exist_ok=True)
    files = [f for f in os.listdir(src_media_dir) if os.path.isfile(os.path.join(src_media_dir, f))]

    if not files:
        print('  No media files to copy')
        return 0

    if dry_run:
        print(f'  Would copy {len(files)} media files')
        return len(files)

    copied = 0
    for fname in files:
        src = os.path.join(src_media_dir, fname)
        dst = os.path.join(dst_media_dir, fname)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied += 1

    print(f'  Media: {copied} files copied ({len(files) - copied} already existed)')
    return copied


def main():
    parser = argparse.ArgumentParser(description='Migrate wa-bot data to sign-house-v3')
    parser.add_argument('--source', required=True, help='Source MongoDB URI (wa-bot)')
    parser.add_argument('--target', required=True, help='Target MongoDB URI (sign-house-v3)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing')
    parser.add_argument('--skip-media', action='store_true', help='Skip media file copy')
    parser.add_argument('--force', action='store_true', help='Overwrite existing target data')
    parser.add_argument('--src-media-dir', default='', help='Source media dir (wa-bot uploads/)')
    parser.add_argument('--dst-media-dir', default='', help='Target media dir (v3 uploads/wa-media/)')
    args = parser.parse_args()

    print(f'{"[DRY RUN] " if args.dry_run else ""}WA-Bot → Sign House v3 Migration')
    print(f'  Source: {args.source}')
    print(f'  Target: {args.target}')
    print()

    src_client = MongoClient(args.source)
    dst_client = MongoClient(args.target)
    src_db = src_client.get_default_database()
    dst_db = dst_client.get_default_database()

    print('=== Collections ===')
    total = 0
    for src_name, dst_name in COLLECTION_MAP.items():
        total += migrate_collection(src_db, dst_db, src_name, dst_name, args.dry_run)

    print()
    print('=== Users ===')
    migrate_users(src_db, dst_db, args.dry_run)

    if not args.skip_media:
        print()
        print('=== Media Files ===')
        src_media = args.src_media_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'sign-house-wa-bot', 'uploads')
        dst_media = args.dst_media_dir or os.path.join(os.path.dirname(__file__), 'uploads', 'wa-media')
        migrate_media(src_media, dst_media, args.dry_run)

    print()
    print(f'Migration {"preview" if args.dry_run else "complete"}! Total documents: {total}')

    src_client.close()
    dst_client.close()


if __name__ == '__main__':
    main()
