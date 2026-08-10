import { User, UserRole } from '../store/authStore'

/**
 * Permission constants
 */
export const PERMISSIONS = {
  // User management
  MANAGE_USERS: 'manage_users',
  CHANGE_USER_ROLES: 'change_user_roles',
  ACTIVATE_DEACTIVATE_USERS: 'activate_deactivate_users',
  
  // Project permissions
  VIEW_ALL_PROJECTS: 'view_all_projects',
  MODIFY_ANY_PROJECT: 'modify_any_project',
  DELETE_ANY_PROJECT: 'delete_any_project',
  
  // Audit logs
  VIEW_AUDIT_LOGS: 'view_audit_logs',
  EXPORT_AUDIT_LOGS: 'export_audit_logs',
  
  // System
  VIEW_SYSTEM_STATS: 'view_system_stats',
} as const

export type Permission = typeof PERMISSIONS[keyof typeof PERMISSIONS]

/**
 * Role-based permission mapping
 */
const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  admin: [
    PERMISSIONS.MANAGE_USERS,
    PERMISSIONS.CHANGE_USER_ROLES,
    PERMISSIONS.ACTIVATE_DEACTIVATE_USERS,
    PERMISSIONS.VIEW_ALL_PROJECTS,
    PERMISSIONS.MODIFY_ANY_PROJECT,
    PERMISSIONS.DELETE_ANY_PROJECT,
    PERMISSIONS.VIEW_AUDIT_LOGS,
    PERMISSIONS.EXPORT_AUDIT_LOGS,
    PERMISSIONS.VIEW_SYSTEM_STATS,
  ],
  manager: [
    PERMISSIONS.VIEW_ALL_PROJECTS,
  ],
  user: [],
}

/**
 * Check if a user has a specific permission
 */
export function hasPermission(user: User | null, permission: Permission): boolean {
  if (!user) return false
  
  const rolePermissions = ROLE_PERMISSIONS[user.role] || []
  return rolePermissions.includes(permission)
}

/**
 * Check if a user has any of the specified permissions
 */
export function hasAnyPermission(user: User | null, permissions: Permission[]): boolean {
  if (!user) return false
  
  return permissions.some(permission => hasPermission(user, permission))
}

/**
 * Check if a user has all of the specified permissions
 */
export function hasAllPermissions(user: User | null, permissions: Permission[]): boolean {
  if (!user) return false
  
  return permissions.every(permission => hasPermission(user, permission))
}

/**
 * Check if user can access all projects
 */
export function canAccessAllProjects(user: User | null): boolean {
  return hasPermission(user, PERMISSIONS.VIEW_ALL_PROJECTS)
}

/**
 * Check if user can manage users
 */
export function canManageUsers(user: User | null): boolean {
  return hasPermission(user, PERMISSIONS.MANAGE_USERS)
}

/**
 * Check if user can view audit logs
 */
export function canViewAuditLogs(user: User | null): boolean {
  return hasPermission(user, PERMISSIONS.VIEW_AUDIT_LOGS)
}

/**
 * Check if user is an admin
 */
export function isAdmin(user: User | null): boolean {
  return user?.role === 'admin'
}

/**
 * Check if user is a manager or higher
 */
export function isManager(user: User | null): boolean {
  return user?.role === 'admin' || user?.role === 'manager'
}

/**
 * Get role display name
 */
export function getRoleDisplayName(role: UserRole): string {
  const roleNames: Record<UserRole, string> = {
    admin: 'Admin',
    manager: 'Manager',
    user: 'User',
  }
  return roleNames[role]
}

/**
 * Get role color class for Tailwind
 */
export function getRoleColorClass(role: UserRole): string {
  const roleColors: Record<UserRole, string> = {
    admin: 'bg-sign-500/15 text-sign-700 dark:bg-sign-500/20 dark:text-sign-400',
    manager: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    user: 'bg-slate-50 text-slate-500 dark:bg-slate-800/50 dark:text-slate-400',
  }
  return roleColors[role]
}

