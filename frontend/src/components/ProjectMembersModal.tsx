import { useState, useEffect } from 'react'
import { X, UserPlus, Trash2, User } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import api from '../lib/api'
import toast from 'react-hot-toast'

interface Member {
  id: string
  username: string
  email: string
  role: 'owner' | 'member'
  added_at: string
}

interface ProjectMembersModalProps {
  projectId: string
  projectName: string
  isOpen: boolean
  onClose: () => void
}

export default function ProjectMembersModal({ 
  projectId, 
  projectName,
  isOpen, 
  onClose 
}: ProjectMembersModalProps) {
  const [owner, setOwner] = useState<Member | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [addingMember, setAddingMember] = useState(false)
  const [searchEmail, setSearchEmail] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)

  useEffect(() => {
    if (isOpen) {
      fetchMembers()
    }
  }, [isOpen, projectId])

  const fetchMembers = async () => {
    setLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/members`)
      setOwner(response.data.owner)
      setMembers(response.data.members)
    } catch (error) {
      console.error('Failed to fetch members:', error)
      toast.error('Failed to load project members')
    } finally {
      setLoading(false)
    }
  }

  const searchUsers = async (email: string) => {
    if (!email.trim()) {
      setSearchResults([])
      return
    }

    setSearching(true)
    try {
      const response = await api.get(`/admin/users?search=${email}&per_page=5`)
      // Filter out owner and existing members
      const filtered = response.data.users.filter((u: any) => 
        u.id !== owner?.id && !members.find(m => m.id === u.id)
      )
      setSearchResults(filtered)
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setSearching(false)
    }
  }

  const handleAddMember = async (userId: string) => {
    try {
      await api.post(`/projects/${projectId}/members`, { user_id: userId })
      toast.success('Member added successfully')
      setSearchEmail('')
      setSearchResults([])
      setAddingMember(false)
      fetchMembers()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to add member')
    }
  }

  const handleRemoveMember = async (memberId: string) => {
    if (!confirm('Are you sure you want to remove this member?')) return

    try {
      await api.delete(`/projects/${projectId}/members/${memberId}`)
      toast.success('Member removed successfully')
      fetchMembers()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to remove member')
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="card p-6 w-full max-w-2xl mx-4 max-h-[80vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-display font-semibold text-slate-900 dark:text-white">
              Project Members
            </h2>
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">{projectName}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Owner */}
            <div className="mb-6">
              <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
                Project Owner
              </h3>
              {owner && (
                <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-gradient-to-br from-sign-500 to-sign-600 rounded-full flex items-center justify-center">
                      <User className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <div className="font-medium text-slate-900 dark:text-white">
                        {owner.username}
                      </div>
                      <div className="text-sm text-slate-500 dark:text-slate-400">
                        {owner.email}
                      </div>
                    </div>
                  </div>
                  <span className="text-xs px-2.5 py-1 bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200 rounded-full font-medium">
                    Owner
                  </span>
                </div>
              )}
            </div>

            {/* Members List */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  Members ({members.length})
                </h3>
                <button
                  onClick={() => setAddingMember(!addingMember)}
                  className="flex items-center gap-2 text-sm px-3 py-1.5 bg-sign-500 hover:bg-sign-600 text-white rounded-lg transition-colors"
                >
                  <UserPlus className="w-4 h-4" />
                  Add Member
                </button>
              </div>

              {/* Add Member Form */}
              <AnimatePresence>
                {addingMember && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mb-4 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg"
                  >
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Search user by email or username
                    </label>
                    <input
                      type="text"
                      placeholder="Enter email or username..."
                      value={searchEmail}
                      onChange={(e) => {
                        setSearchEmail(e.target.value)
                        searchUsers(e.target.value)
                      }}
                      className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg focus:ring-2 focus:ring-sign-500 dark:bg-slate-700 dark:text-white mb-2"
                    />

                    {searching && (
                      <div className="text-sm text-slate-500 dark:text-slate-400 py-2">
                        Searching...
                      </div>
                    )}

                    {searchResults.length > 0 && (
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {searchResults.map((user) => (
                          <button
                            key={user.id}
                            onClick={() => handleAddMember(user.id)}
                            className="w-full flex items-center justify-between p-2 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors text-left"
                          >
                            <div>
                              <div className="font-medium text-slate-900 dark:text-white text-sm">
                                {user.username}
                              </div>
                              <div className="text-xs text-slate-500 dark:text-slate-400">
                                {user.email}
                              </div>
                            </div>
                            <UserPlus className="w-4 h-4 text-sign-500" />
                          </button>
                        ))}
                      </div>
                    )}

                    {searchEmail && !searching && searchResults.length === 0 && (
                      <div className="text-sm text-slate-500 dark:text-slate-400 py-2">
                        No users found
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Members List */}
              {members.length === 0 ? (
                <div className="text-center py-8 text-slate-500 dark:text-slate-400">
                  <User className="w-12 h-12 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">No members yet</p>
                  <p className="text-xs mt-1">Add members to collaborate on this project</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {members.map((member) => (
                    <div
                      key={member.id}
                      className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg"
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-slate-200 dark:bg-slate-700 rounded-full flex items-center justify-center">
                          <User className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                        </div>
                        <div>
                          <div className="font-medium text-slate-900 dark:text-white">
                            {member.username}
                          </div>
                          <div className="text-sm text-slate-500 dark:text-slate-400">
                            {member.email}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleRemoveMember(member.id)}
                        className="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                        title="Remove member"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Close Button */}
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </>
        )}
      </motion.div>
    </div>
  )
}

