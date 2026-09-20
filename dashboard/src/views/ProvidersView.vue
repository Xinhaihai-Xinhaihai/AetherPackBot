<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getProviders, updateBrainConfig, getMcp, bindMcp } from '@/services/api'

interface Capabilities {
  temperature: number
  enable_tools: boolean
  enable_vision: boolean
  enable_text: boolean
  max_tokens: number | null
  stream: boolean
}

interface Provider {
  id: string
  name?: string
  display_name?: string
  model: string
  dialect?: string
  lane?: string
  healthy?: boolean
  timeout?: number
  capabilities?: Capabilities
}

interface McpServer {
  id: string
  name: string
  enabled: boolean
  transport: string
  url?: string
  command?: string
  ok?: boolean
  hint?: string
  bind_models: string[]
  tools?: Array<{ name: string; description: string }>
}

const providers = ref<Provider[]>([])
const mcpServers = ref<McpServer[]>([])
const loading = ref(true)
const error = ref('')
const savingId = ref('')
const notice = ref('')

const drafts = ref<Record<string, Capabilities>>({})
const mcpDrafts = ref<Record<string, string>>({})

function defaultCaps(): Capabilities {
  return {
    temperature: 0.7,
    enable_tools: true,
    enable_vision: true,
    enable_text: true,
    max_tokens: null,
    stream: false
  }
}

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    providers.value = await getProviders()
    for (const p of providers.value) {
      drafts.value[p.id] = { ...defaultCaps(), ...(p.capabilities || {}) }
    }
    try {
      mcpServers.value = await getMcp()
      for (const s of mcpServers.value) {
        mcpDrafts.value[s.id] = (s.bind_models || []).join(', ')
      }
    } catch {
      mcpServers.value = []
    }
  } catch (e) {
    error.value = '获取提供者列表失败'
  } finally {
    loading.value = false
  }
}

async function saveCaps(id: string) {
  savingId.value = id
  notice.value = ''
  try {
    const snap = await updateBrainConfig(id, drafts.value[id])
    const target = providers.value.find(p => p.id === id)
    if (target) target.capabilities = snap.capabilities
    notice.value = `${id} 旋钮已保存`
  } catch (e) {
    error.value = `${id} 保存失败`
  } finally {
    savingId.value = ''
  }
}

async function saveBind(serverId: string) {
  savingId.value = serverId
  notice.value = ''
  try {
    const models = (mcpDrafts.value[serverId] || '')
      .split(/[,\s]+/)
      .map(s => s.trim())
      .filter(Boolean)
    const snap = await bindMcp(serverId, models)
    const target = mcpServers.value.find(s => s.id === serverId)
    if (target) target.bind_models = snap.bind_models || models
    notice.value = `${serverId} 已绑定 ${models.join(', ') || '全部模型'}`
  } catch (e) {
    error.value = `${serverId} 绑定失败`
  } finally {
    savingId.value = ''
  }
}

onMounted(fetchAll)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">LLM 提供者</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1">每个模型单独一套旋钮，MCP 单独绑定多个模型</p>
      </div>
    </div>

    <div v-if="notice" class="mb-4 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 text-sm text-green-700 dark:text-green-300">{{ notice }}</div>

    <div v-if="loading" class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else-if="error && providers.length === 0" class="card">
      <div class="text-center py-8">
        <p class="text-red-500">{{ error }}</p>
        <button @click="fetchAll" class="btn-primary mt-4">重试</button>
      </div>
    </div>

    <div v-else class="space-y-10">
      <div v-if="providers.length === 0" class="card text-center py-12">
        <h3 class="text-lg font-medium text-gray-900 dark:text-white">暂无提供者</h3>
        <p class="text-gray-500 dark:text-gray-400 mt-2">把模型写进 data/config/config.json 的 providers</p>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div v-for="provider in providers" :key="provider.id" class="card">
          <div class="flex items-start justify-between">
            <div>
              <h3 class="font-semibold text-gray-900 dark:text-white">{{ provider.name || provider.id }}</h3>
              <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{{ provider.model }} · {{ provider.dialect }} · {{ provider.lane }}</p>
            </div>
            <span :class="provider.healthy ? 'badge-success' : 'badge-warning'">{{ provider.healthy ? '活跃' : '待测' }}</span>
          </div>

          <div class="mt-5 space-y-4" v-if="drafts[provider.id]">
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="text-sm text-gray-700 dark:text-gray-300">温度</label>
                <span class="text-sm font-medium text-gray-900 dark:text-white">{{ drafts[provider.id].temperature }}</span>
              </div>
              <input v-model.number="drafts[provider.id].temperature" type="range" min="0" max="2" step="0.1" class="w-full" />
            </div>

            <div class="grid grid-cols-3 gap-3 text-sm">
              <label class="flex items-center gap-2">
                <input v-model="drafts[provider.id].enable_text" type="checkbox" />
                文本
              </label>
              <label class="flex items-center gap-2">
                <input v-model="drafts[provider.id].enable_tools" type="checkbox" />
                工具
              </label>
              <label class="flex items-center gap-2">
                <input v-model="drafts[provider.id].enable_vision" type="checkbox" />
                图像
              </label>
            </div>

            <div>
              <label class="block text-sm text-gray-700 dark:text-gray-300 mb-1">max_tokens</label>
              <input v-model.number="drafts[provider.id].max_tokens" type="number" class="input" placeholder="空=不限" />
            </div>

            <button class="btn-primary w-full" :disabled="savingId === provider.id" @click="saveCaps(provider.id)">
              {{ savingId === provider.id ? '保存中' : '保存此模型' }}
            </button>
          </div>
        </div>
      </div>

      <div>
        <h2 class="text-xl font-bold text-gray-900 dark:text-white mb-2">MCP 服务</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">单独一层。一个 MCP 可绑定多个模型，逗号分隔。留空=全部模型。</p>

        <div v-if="mcpServers.length === 0" class="card text-sm text-gray-500">还没有 MCP。按 data/config/config.example.json 的 mcp.servers 写。</div>

        <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div v-for="server in mcpServers" :key="server.id" class="card">
            <div class="flex items-start justify-between">
              <div>
                <h3 class="font-semibold text-gray-900 dark:text-white">{{ server.name || server.id }}</h3>
                <p class="text-sm text-gray-500 mt-1">{{ server.transport }} · {{ server.ok ? '在线' : '离线' }} · {{ server.hint }}</p>
              </div>
              <span :class="server.enabled ? 'badge-info' : 'badge-warning'">{{ server.enabled ? '开' : '关' }}</span>
            </div>
            <p class="text-xs text-gray-500 mt-3" v-if="server.tools?.length">工具: {{ server.tools.map(t => t.name).join(', ') }}</p>
            <label class="block text-sm mt-4 mb-1 text-gray-700 dark:text-gray-300">绑定模型 id</label>
            <input v-model="mcpDrafts[server.id]" class="input" placeholder="ppo, huachuan" />
            <button class="btn-primary w-full mt-3" :disabled="savingId === server.id" @click="saveBind(server.id)">
              {{ savingId === server.id ? '绑定中' : '保存绑定' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
