# RBAC Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### Step 1: Run the Migration
```bash
cd backend
python migrate_add_roles.py
```

This will:
- Add role fields to all existing users
- Make the first user an admin
- Create necessary database indexes

### Step 2: Start the Application
```bash
# Terminal 1 - Backend
cd backend
source venv/bin/activate
python run.py

# Terminal 2 - Frontend
cd frontend
npm run dev
```

### Step 3: Access Admin Features

1. **Login** as the admin user (first registered user)
2. **Navigate** to `/admin` to manage users
3. **Navigate** to `/audit-logs` to view system activity

## 📋 Quick Reference

### User Roles

| Role | Can Do |
|------|--------|
| **Admin** | Everything - manage users, view all projects, access audit logs |
| **Manager** | View all projects, manage own projects |
| **User** | Create and manage only their own projects |

### Admin URLs

- **User Management**: `http://localhost:3000/admin`
- **Audit Logs**: `http://localhost:3000/audit-logs`

### Common Tasks

#### Make a User Admin
```bash
cd backend
python migrate_add_roles.py --admin-email user@example.com
```

#### Change User Role (via UI)
1. Login as admin
2. Go to `/admin`
3. Use dropdown to change user's role
4. Changes take effect immediately

#### View Audit Logs (via UI)
1. Login as admin
2. Go to `/audit-logs`
3. Use filters to search by action, date, etc.

## 🔑 Key Features

### For Admins
- ✅ User management interface at `/admin`
- ✅ Change user roles and status
- ✅ View all projects from all users
- ✅ Access audit logs at `/audit-logs`
- ✅ See system statistics

### For Managers
- ✅ View all projects (with owner names)
- ✅ Create and manage own projects
- ✅ Export data from any project

### For Users
- ✅ Create projects
- ✅ Manage own projects
- ✅ Cannot see other users' projects

## 🎯 Testing Checklist

Quick tests to verify RBAC is working:

- [ ] First user has admin role (check in `/admin`)
- [ ] Admin can see "User Management" in navigation
- [ ] Admin can see "Audit Logs" in navigation
- [ ] Admin can change a user's role
- [ ] Manager can see all projects
- [ ] Regular user only sees own projects
- [ ] Regular user gets redirected from `/admin`
- [ ] Audit logs show recent actions

## 🛠️ Troubleshooting

### "Access Denied" when accessing /admin
**Solution**: Verify your user has admin role
```bash
# Check in MongoDB
db.users.findOne({email: "your@email.com"})
# Should show: role: "admin"
```

### Migration Script Fails
**Solution**: Ensure MongoDB is running and accessible
```bash
# Check MongoDB connection
mongosh "mongodb://localhost:27017/signhouse_dev"
```

### Changes Not Appearing
**Solution**: Clear browser storage and re-login
1. Open DevTools (F12)
2. Application → Storage → Clear site data
3. Refresh page and login again

## 📚 More Information

- **Full Documentation**: See `RBAC_IMPLEMENTATION.md`
- **Summary**: See `RBAC_SUMMARY.md`
- **Main README**: See `README.md`

## 🎉 You're Ready!

Your RBAC system is now active. Admins can manage users, everyone has appropriate access levels, and all actions are logged for audit purposes.

