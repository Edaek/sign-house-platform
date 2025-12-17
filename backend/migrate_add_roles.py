#!/usr/bin/env python3
"""
Migration script to add RBAC roles to existing users.
This script should be run once after deploying the RBAC changes.

Usage:
    python migrate_add_roles.py [--admin-email EMAIL]
"""
import sys
import os
import argparse
from datetime import datetime

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pymongo import MongoClient
from config import config

def migrate_add_roles(admin_email=None):
    """Add role field to existing users."""
    
    # Get config
    app_config = config['development']
    mongo_uri = app_config.MONGO_URI
    
    print(f"Connecting to MongoDB: {mongo_uri}")
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    # Count users without role field
    users_without_role = db.users.count_documents({'role': {'$exists': False}})
    print(f"\nFound {users_without_role} users without role field")
    
    if users_without_role == 0:
        print("All users already have roles assigned. Migration not needed.")
        return
    
    # Update all users without role to have 'user' role
    result = db.users.update_many(
        {'role': {'$exists': False}},
        {
            '$set': {
                'role': 'user',
                'role_changed_at': None,
                'role_assigned_by': None,
                'updated_at': datetime.utcnow()
            }
        }
    )
    
    print(f"Updated {result.modified_count} users with default 'user' role")
    
    # If admin_email provided, make that user an admin
    if admin_email:
        user = db.users.find_one({'email': admin_email})
        if user:
            db.users.update_one(
                {'_id': user['_id']},
                {
                    '$set': {
                        'role': 'admin',
                        'role_changed_at': datetime.utcnow(),
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            print(f"\n✓ User '{user['username']}' ({admin_email}) has been made an admin")
        else:
            print(f"\n✗ No user found with email: {admin_email}")
    else:
        # Make the first user an admin if no admin exists
        admin_count = db.users.count_documents({'role': 'admin'})
        if admin_count == 0:
            first_user = db.users.find_one({}, sort=[('created_at', 1)])
            if first_user:
                db.users.update_one(
                    {'_id': first_user['_id']},
                    {
                        '$set': {
                            'role': 'admin',
                            'role_changed_at': datetime.utcnow(),
                            'updated_at': datetime.utcnow()
                        }
                    }
                )
                print(f"\n✓ First user '{first_user['username']}' has been made an admin")
    
    # Create indexes if they don't exist
    print("\nCreating indexes...")
    db.users.create_index('role')
    db.audit_logs.create_index('user_id')
    db.audit_logs.create_index('timestamp')
    db.audit_logs.create_index([('user_id', 1), ('timestamp', -1)])
    print("✓ Indexes created")
    
    # Print summary
    print("\n" + "="*50)
    print("MIGRATION SUMMARY")
    print("="*50)
    
    admin_count = db.users.count_documents({'role': 'admin'})
    manager_count = db.users.count_documents({'role': 'manager'})
    user_count = db.users.count_documents({'role': 'user'})
    total_users = db.users.count_documents({})
    
    print(f"Total users: {total_users}")
    print(f"  - Admins: {admin_count}")
    print(f"  - Managers: {manager_count}")
    print(f"  - Users: {user_count}")
    print("\n✓ Migration completed successfully!")
    
    client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Migrate existing users to add RBAC roles'
    )
    parser.add_argument(
        '--admin-email',
        type=str,
        help='Email of the user to make admin (optional)'
    )
    
    args = parser.parse_args()
    
    try:
        migrate_add_roles(admin_email=args.admin_email)
    except Exception as e:
        print(f"\n✗ Migration failed: {str(e)}")
        sys.exit(1)

