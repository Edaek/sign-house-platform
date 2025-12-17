# RBAC Implementation Guide

This document describes the Role-Based Access Control (RBAC) system implemented in Sign House.

## Overview

The application now supports three user roles with different permission levels:

- **Admin**: Full system access - manage users, assign roles, view all projects, access audit logs
- **Manager**: Project oversight - view all projects, export data, manage own projects
- **User**: Standard access - create and manage own projects only

## Role Permissions

### Admin
- View and manage all users
- Assign and change user roles
- Activate/deactivate user accounts
- View all projects (from all users)
- Modify and delete any project
- View audit logs
- Access system statistics

### Manager
- View all projects (from all users)
- Create and manage own projects
- Export data from accessible projects

### User
- Create projects
- View and manage only their own projects
- Export data from their own projects

## Database Changes

### Users Collection
New fields added:
```javascript
{
  role: "admin" | "manager" | "user",  // Default: "user"
  role_changed_at: datetime,           // When role was last changed
  role_assigned_by: ObjectId           // Admin who changed the role
}
```

### Audit Logs Collection (New)
```javascript
{
  user_id: ObjectId,
  action: string,                      // e.g., "login", "project_created"
  resource_type: string,               // e.g., "project", "user"
  resource_id: string,
  details: object,
  ip_address: string,
  user_agent: string,
  timestamp: datetime
}
```

## Backend Implementation

### Permission Decorators

Located in `backend/app/utils/permissions.py`:

```python
# Require specific role(s)
@require_role('admin')
@require_role('admin', 'manager')

# Check project access (read)
@require_project_access

# Check project modification rights (write)
@require_project_modify
```

### Audit Logging

Located in `backend/app/services/audit_service.py`:

```python
# Log an action
log_action(
    user_id=user_id,
    action='project_created',
    resource_type='project',
    resource_id=project_id,
    details={'project_name': 'My Project'}
)

# Get audit logs with filters
get_audit_logs(
    filters={'user_id': user_id, 'action': 'login'},
    page=1,
    per_page=50
)
```

### API Endpoints

#### Admin Endpoints (`/api/admin/*`)

All require Admin role:

- `GET /api/admin/users` - List all users with filtering
- `GET /api/admin/users/:id` - Get user details
- `PUT /api/admin/users/:id/role` - Change user role
- `PUT /api/admin/users/:id/status` - Activate/deactivate user
- `GET /api/admin/audit-logs` - View audit logs
- `GET /api/admin/stats` - System statistics

#### Updated Project Endpoints

All project endpoints now check permissions:
- List projects: Users see own, Managers/Admins see all
- View project: Check ownership or elevated role
- Modify project: Check ownership or Admin role
- Delete project: Check ownership or Admin role

## Frontend Implementation

### Auth Store Updates

Located in `frontend/src/store/authStore.ts`:

New permission checking methods:
```typescript
isAdmin()                              // Check if user is admin
isManager()                            // Check if user is manager or admin
canAccessAllProjects()                 // Check if can view all projects
canManageUsers()                       // Check if can manage users
canViewAuditLogs()                     // Check if can view audit logs
canAccessProject(projectOwnerId)       // Check if can access specific project
canModifyProject(projectOwnerId)       // Check if can modify specific project
```

### Permission Utilities

Located in `frontend/src/lib/permissions.ts`:

```typescript
import { hasPermission, PERMISSIONS } from '../lib/permissions'

// Check specific permission
if (hasPermission(user, PERMISSIONS.MANAGE_USERS)) {
  // Show user management UI
}

// Get role display info
getRoleDisplayName(role)               // "Admin", "Manager", "User"
getRoleColorClass(role)                // Tailwind classes for badges
```

### New Components

#### RoleBadge
Visual indicator for user roles with color coding:
```tsx
import RoleBadge from '../components/RoleBadge'

<RoleBadge role={user.role} size="sm" />
```

#### AdminPage
User management interface at `/admin`:
- Search and filter users
- View user details and project counts
- Change user roles
- Activate/deactivate users

#### AuditLogsPage
Audit log viewer at `/audit-logs`:
- View all system actions
- Filter by action, resource type, date range
- See user, timestamp, IP address
- View detailed action information

### Navigation Updates

The Layout component now shows role-specific navigation:
- All users see "Dashboard" (or "All Projects" for Managers)
- Admins see "User Management" and "Audit Logs" links
- User's role badge is displayed in the header

## Migration

### For New Installations

No migration needed. The first registered user automatically becomes an Admin.

### For Existing Installations

Run the migration script:

```bash
cd backend
python migrate_add_roles.py
```

To make a specific user an admin:

```bash
python migrate_add_roles.py --admin-email admin@example.com
```

The script will:
1. Add `role` field to all existing users (default: "user")
2. Make the specified user (or first user) an admin
3. Create necessary indexes
4. Display a summary of role distribution

## Testing

### Test Scenarios

1. **Role Assignment**
   - Register new user (should be "user" role, unless first user)
   - Admin changes user role
   - Verify role persists after logout/login

2. **Permission Enforcement**
   - Regular user cannot access `/admin` or `/audit-logs`
   - Regular user cannot see other users' projects
   - Manager can view all projects
   - Admin can modify any project

3. **Project Access**
   - User A creates project
   - User B cannot access User A's project
   - Manager can view User A's project
   - Admin can modify User A's project

4. **Audit Logging**
   - Login creates audit log entry
   - Project creation/deletion logged
   - Role changes logged with admin who made change
   - Failed permission attempts logged

### Manual Testing Steps

1. **Setup Test Users**
   ```bash
   # Register 3 users: admin@test.com, manager@test.com, user@test.com
   # Use migration script to set roles
   python migrate_add_roles.py --admin-email admin@test.com
   ```

2. **Test Admin Functions**
   - Login as admin
   - Navigate to `/admin`
   - Change manager@test.com role to "manager"
   - View audit logs at `/audit-logs`
   - Verify role change is logged

3. **Test Manager Functions**
   - Login as manager
   - Create a project
   - Verify you can see projects from all users
   - Verify you cannot access `/admin`

4. **Test User Functions**
   - Login as regular user
   - Create a project
   - Verify you only see your own projects
   - Verify you cannot access `/admin` or `/audit-logs`

5. **Test Project Permissions**
   - As user, try to access manager's project URL directly
   - Should get "Access denied" error
   - As manager, access user's project
   - Should succeed (read-only)

## Security Considerations

1. **Backend Enforcement**: All permission checks happen on the backend. Frontend checks are only for UI convenience.

2. **JWT Claims**: User role is included in JWT token for efficient permission checking without database lookups.

3. **Audit Immutability**: Audit logs are insert-only. No updates or deletes allowed.

4. **Role Change Tracking**: All role changes are logged with the admin who made the change.

5. **Failed Attempts**: Failed permission attempts are logged for security monitoring.

## API Response Changes

### User Object
Now includes `role` field:
```json
{
  "id": "...",
  "username": "john",
  "email": "john@example.com",
  "role": "user",
  "created_at": "...",
  "is_active": true
}
```

### Project List (for Managers/Admins)
Includes owner information:
```json
{
  "id": "...",
  "name": "Project Name",
  "owner_username": "john",
  "owner_id": "...",
  ...
}
```

## Troubleshooting

### Users can't access admin features
- Verify user has `role: "admin"` in database
- Check JWT token includes correct role
- Clear browser storage and re-login

### Migration fails
- Ensure MongoDB is running
- Check MONGO_URI in config
- Verify pymongo is installed

### Audit logs not appearing
- Check MongoDB indexes are created
- Verify audit_service is imported correctly
- Check for errors in backend logs

### Permission denied errors
- Verify user is authenticated
- Check user's role in database
- Ensure decorators are applied to endpoints

## Future Enhancements

Possible additions to the RBAC system:

1. **Project-level Permissions**: Allow sharing projects with specific users
2. **Custom Roles**: Define custom roles with specific permission sets
3. **Role Hierarchies**: More granular role levels
4. **Audit Log Export**: Export audit logs to CSV/Excel
5. **User Groups**: Group users for easier permission management
6. **Two-Factor Authentication**: Enhanced security for admin accounts
7. **Session Management**: View and revoke active sessions
8. **API Keys**: Generate API keys with specific permissions

## Support

For issues or questions about the RBAC implementation:
1. Check this documentation
2. Review audit logs for permission errors
3. Verify database migration completed successfully
4. Check backend logs for detailed error messages

