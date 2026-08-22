import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'
import { api } from '@/api/client'

interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  mfaPending: boolean

  setAuth: (user: User, accessToken: string, refreshToken: string) => void
  setMfaPending: (pending: boolean) => void
  logout: () => void
  refreshAuth: () => Promise<void>
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: true,
      mfaPending: false,

      setAuth: (user, accessToken, refreshToken) => {
        set({
          user,
          accessToken,
          refreshToken,
          isAuthenticated: true,
          isLoading: false,
          mfaPending: false,
        })
      },

      setMfaPending: (pending) => {
        set({ mfaPending: pending })
      },

      logout: () => {
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          isLoading: false,
          mfaPending: false,
        })
      },

      refreshAuth: async () => {
        const { refreshToken } = get()
        if (!refreshToken) {
          get().logout()
          return
        }

        try {
          const response = await api.post('/auth/refresh', {
            refresh_token: refreshToken,
          })
          // /auth/refresh returns tokens ONLY (no user). Destructuring `user`
          // here previously set user=undefined, which downgraded an admin to a
          // non-admin nav until a full reload. Keep the tokens, then (re)load the
          // user from /auth/me so is_admin etc. are populated.
          const { access_token, refresh_token } = response.data
          set({
            accessToken: access_token,
            refreshToken: refresh_token,
            isAuthenticated: true,
          })
          try {
            const me = await api.get('/auth/me')
            set({ user: me.data })
          } catch {
            // Backend still coming up (e.g. right after an update): keep the
            // existing user rather than blanking the menu; checkAuth/interceptor retries.
          }
        } catch {
          get().logout()
        }
      },

      checkAuth: async () => {
        const { accessToken } = get()
        if (!accessToken) {
          set({ isLoading: false })
          return
        }

        try {
          const response = await api.get('/auth/me')
          set({
            user: response.data,
            isAuthenticated: true,
            isLoading: false,
          })
        } catch {
          // Try to refresh
          await get().refreshAuth()
          set({ isLoading: false })
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
      }),
    }
  )
)
