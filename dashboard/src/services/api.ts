import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.DEV ? '' : window.location.origin,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// API functions
export async function getStatus() {
  const response = await api.get('/api/status')
  return response.data
}

export async function getConfig() {
  const response = await api.get('/api/config')
  return response.data
}

export async function updateConfig(data: Record<string, any>) {
  const response = await api.put('/api/config', data)
  return response.data
}

function asList<T = any>(data: any): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && Array.isArray(data.items)) return data.items as T[]
  return []
}

export async function getProviders() {
  const response = await api.get('/api/providers')
  return asList(response.data)
}

export async function pulseBrains() {
  const response = await api.post('/api/brains/pulse')
  return response.data
}

export async function getPlatforms() {
  const response = await api.get('/api/platforms')
  return asList(response.data)
}

export async function addPlatform(data: Record<string, any>) {
  const response = await api.post('/api/platforms', data)
  return response.data
}

export async function startPlatform(id: string) {
  const response = await api.post(`/api/platforms/${id}/start`)
  return response.data
}

export async function stopPlatform(id: string) {
  const response = await api.post(`/api/platforms/${id}/stop`)
  return response.data
}

export async function deletePlatform(id: string) {
  const response = await api.delete(`/api/platforms/${id}`)
  return response.data
}

export async function getPlugins() {
  const response = await api.get('/api/plugins')
  return asList(response.data)
}

export async function reloadPlugin(name: string) {
  const response = await api.post(`/api/plugins/${name}/reload`)
  return response.data
}

export async function uninstallPlugin(name: string) {
  const response = await api.delete(`/api/plugins/${name}`)
  return response.data
}

export async function getTools() {
  const response = await api.get('/api/tools')
  return asList(response.data)
}

export async function getLogs(count: number = 100) {
  const response = await api.get('/api/logs', { params: { count } })
  return response.data
}

export async function updateBrainConfig(id: string, data: Record<string, any>) {
  const response = await api.put(`/api/brains/${id}/config`, data)
  return response.data
}

export async function getMcp() {
  const response = await api.get('/api/mcp')
  return asList(response.data)
}

export async function bindMcp(serverId: string, models: string[]) {
  const response = await api.put(`/api/mcp/${serverId}/bind`, { bind_models: models })
  return response.data
}

export async function addMcp(data: Record<string, any>) {
  const response = await api.post('/api/mcp', data)
  return response.data
}

export async function deleteMcp(serverId: string) {
  const response = await api.delete(`/api/mcp/${serverId}`)
  return response.data
}
