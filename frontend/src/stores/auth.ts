import { create } from 'zustand'
import type { User } from '@/types'
import { api } from '@/api/client'

// H3: the access token lives in memory only (never persisted to localStorage),
// and the refresh token is an HttpOnly cookie the browser sends automatically.
// On a full reload the access token is gone, so the app bootstraps the session
// from the refresh cookie via checkAuth() -> refreshAuth().

interface AuthState {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  mfaPending: boolean

  setAuth: (user: User, accessToken: string) => void
  setMfaPending: (pending: boolean) => void
  logout: () => void
  refreshAuth: () => Promise<void>
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: true,
  mfaPending: false,

  setAuth: (user, accessToken) => {
    set({
      user,
      accessToken,
      isAuthenticated: true,
      isLoading: false,
      mfaPending: false,
    })
  },

  setMfaPending: (pending) => {
    set({ mfaPending: pending })
  },

  logout: () => {
    // Best-effort: clear the server-side refresh cookie. Fire-and-forget so the
    // UI logs out immediately even if the request fails.
    api.post('/auth/logout').catch(() => {})
    set({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isLoading: false,
      mfaPending: false,
    })
  },

  refreshAuth: async () => {
    try {
      // The refresh token is the HttpOnly cookie; no token is sent from JS.
      const response = await api.post('/auth/refresh', {})
      const { access_token } = response.data
      set({ accessToken: access_token, isAuthenticated: true })
      try {
        const me = await api.get('/auth/me')
        set({ user: me.data })
      } catch {
        // Backend still coming up (e.g. right after an update): keep the existing
        // user rather than blanking the menu; checkAuth/interceptor retries.
      }
    } catch {
      get().logout()
    }
  },

  checkAuth: async () => {
    const { accessToken } = get()
    // No in-memory access token (e.g. after a reload): try to bootstrap the
    // session from the refresh cookie.
    if (!accessToken) {
      await get().refreshAuth()
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
      // Access token rejected: try a cookie refresh before giving up.
      await get().refreshAuth()
      set({ isLoading: false })
    }
  },
}))
