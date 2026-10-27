import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import ProjectPage from './pages/ProjectPage'
import EditorPage from './pages/EditorPage'
import ExportPage from './pages/ExportPage'
import AdminPage from './pages/AdminPage'
import AuditLogsPage from './pages/AuditLogsPage'
import DictionaryPage from './pages/DictionaryPage'
import WaLayout from './pages/wa/WaLayout'
import WaDashboardPage from './pages/wa/WaDashboardPage'
import WaProjectsPage from './pages/wa/WaProjectsPage'
import WaProjectDetailPage from './pages/wa/WaProjectDetailPage'
import WaImagePoolPage from './pages/wa/WaImagePoolPage'
import WaSearchPage from './pages/wa/WaSearchPage'
import WaKeywordsPage from './pages/wa/WaKeywordsPage'
import WaTemplatesPage from './pages/wa/WaTemplatesPage'
import WaManageProjectsPage from './pages/wa/WaManageProjectsPage'
import WaSystemPage from './pages/wa/WaSystemPage'
import WaUsersPage from './pages/wa/WaUsersPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="project/:projectId" element={<ProjectPage />} />
        <Route path="project/:projectId/floor/:floorId" element={<EditorPage />} />
        <Route path="project/:projectId/export" element={<ExportPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="audit-logs" element={<AuditLogsPage />} />
        <Route path="dictionary" element={<DictionaryPage />} />

        <Route path="wa" element={<WaLayout />}>
          <Route index element={<WaDashboardPage />} />
          <Route path="projects" element={<WaProjectsPage />} />
          <Route path="projects/:id" element={<WaProjectDetailPage />} />
          <Route path="image-pool" element={<WaImagePoolPage />} />
          <Route path="search" element={<WaSearchPage />} />
          <Route path="admin/keywords" element={<WaKeywordsPage />} />
          <Route path="admin/templates" element={<WaTemplatesPage />} />
          <Route path="admin/projects" element={<WaManageProjectsPage />} />
          <Route path="admin/system" element={<WaSystemPage />} />
          <Route path="admin/users" element={<WaUsersPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
