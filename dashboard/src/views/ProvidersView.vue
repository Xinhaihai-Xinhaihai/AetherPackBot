<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getProviders, updateBrainConfig, getMcp, bindMcp, addMcp, deleteMcp, pulseBrains } from '@/services/api'
import { useI18n } from '@/i18n'

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
  model: string
  dialect?: string
  lane?: string
  healthy?: boolean
  capabilities?: Capabilities
}

interface McpServer {
  id: string
  name: string
  enabled: boolean
  transport: string
  ok?: boolean
  hint?: string
  bind_models: string[]
  tools?: Array<{ name: string }>
}

const { t } = useI18n()
const providers = ref<Provider[]>([])
const mcpServers = ref<McpServer[]>([])
const loading = ref(true)
const error = ref('')
const savingId = ref('')
const notice = ref('')
const drafts = ref<Record<string, Capabilities>>({})
const mcpDrafts = ref<Record<string, string>>({})
const showAdd = ref(false)
const mcpForm = ref({ id: '', name: '', transport: 'stdio', url: '', command: '', args: '', bind_models: '' })

function defaultCaps(): Capabilities {
  return { temperature: 0.7, enable_tools: true, enable_vision: true, enable_text: true, max_tokens: null, stream: false }
}

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    providers.value = await getProviders()
    for (const p of providers.value) drafts.value[p.id] = { ...defaultCaps(), ...(p.capabilities || {}) }
    mcpServers.value = await getMcp()
    for (const s of mcpServers.value) mcpDrafts.value[s.id] = (s.bind_models || []).join(', ')
  } catch (e) {
    error.value = t.value.providers.fail
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
    notice.value = `${id} ${t.value.providers.saved}`
  } catch {
    error.value = `${id} ${t.value.providers.saveFail}`
  } finally {
    savingId.value = ''
  }
}

async function pulse() {
  savingId.value = 'pulse'
  try {
    const map = await pulseBrains()
    for (const p of providers.value) {
      if (map[p.id]) p.healthy = !!map[p.id].ok
    }
    notice.value = t.value.common.ok
  } catch {
    error.value = t.value.providers.fail
  } finally {
    savingId.value = ''
  }
}

async function saveBind(serverId: string) {
  savingId.value = serverId
  try {
    const models = (mcpDrafts.value[serverId] || '').split(/[,\s]+/).map(s => s.trim()).filter(Boolean)
    const snap = await bindMcp(serverId, models)
    const target = mcpServers.value.find(s => s.id === serverId)
    if (target) target.bind_models = snap.bind_models || models
    notice.value = `${serverId} ${t.value.providers.mcpBindOk} ${models.join(', ') || t.value.providers.mcpAll}`
  } catch {
    error.value = `${serverId} ${t.value.providers.saveFail}`
  } finally {
    savingId.value = ''
  }
}

async function submitMcp() {
  savingId.value = 'add-mcp'
  try {
    const args = mcpForm.value.args.split(/[,\s]+/).map(s => s.trim()).filter(Boolean)
    const bind = mcpForm.value.bind_models.split(/[,\s]+/).map(s => s.trim()).filter(Boolean)
    await addMcp({
      id: mcpForm.value.id || `mcp_${Date.now()}`,
      name: mcpForm.value.name || mcpForm.value.id,
      transport: mcpForm.value.transport,
      url: mcpForm.value.url,
      command: mcpForm.value.command,
      args,
      bind_models: bind,
      enabled: true,
    })
    showAdd.value = false
    notice.value = t.value.providers.mcpAdded
    await fetchAll()
  } catch {
    error.value = t.value.providers.saveFail
  } finally {
    savingId.value = ''
  }
}

async function removeMcp(id: string) {
  if (!confirm(id)) return
  try {
    await deleteMcp(id)
    mcpServers.value = mcpServers.value.filter(s => s.id !== id)
    notice.value = t.value.common.ok
  } catch {
    error.value = t.value.providers.saveFail
  }
}

onMounted(fetchAll)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t.providers.title }}</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t.providers.sub }}</p>
      </div>
      <button type="button" class="btn-secondary" :disabled="savingId === 'pulse'" @click="pulse">
        {{ savingId === 'pulse' ? t.providers.pulsing : t.providers.pulse }}
      </button>
    </div>

    <div v-if="notice" class="mb-4 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 text-sm text-green-700 dark:text-green-300">{{ notice }}</div>
    <div v-if="error && !loading" class="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-sm text-red-600">{{ error }}</div>

    <div v-if="loading" class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else class="space-y-10">
      <div v-if="providers.length === 0" class="card text-center py-12">
        <h3 class="text-lg font-medium text-gray-900 dark:text-white">{{ t.providers.empty }}</h3>
        <p class="text-gray-500 mt-2">{{ t.providers.emptyHint }}</p>
        <button type="button" class="btn-primary mt-4" @click="fetchAll">{{ t.common.retry }}</button>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div v-for="provider in providers" :key="provider.id" class="card">
          <div class="flex items-start justify-between">
            <div>
              <h3 class="font-semibold text-gray-900 dark:text-white">{{ provider.name || provider.id }}</h3>
              <p class="text-sm text-gray-500 mt-1">{{ provider.model }} · {{ provider.dialect }} · {{ provider.lane }}</p>
            </div>
            <span :class="provider.healthy ? 'badge-success' : 'badge-warning'">{{ provider.healthy ? t.providers.active : t.providers.waiting }}</span>
          </div>
          <div class="mt-5 space-y-4" v-if="drafts[provider.id]">
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="text-sm text-gray-700 dark:text-gray-300">{{ t.providers.temp }}</label>
                <span class="text-sm font-medium">{{ drafts[provider.id].temperature }}</span>
              </div>
              <input v-model.number="drafts[provider.id].temperature" type="range" min="0" max="2" step="0.1" class="w-full" />
            </div>
            <div class="grid grid-cols-3 gap-3 text-sm">
              <label class="flex items-center gap-2"><input v-model="drafts[provider.id].enable_text" type="checkbox" />{{ t.providers.text }}</label>
              <label class="flex items-center gap-2"><input v-model="drafts[provider.id].enable_tools" type="checkbox" />{{ t.providers.tools }}</label>
              <label class="flex items-center gap-2"><input v-model="drafts[provider.id].enable_vision" type="checkbox" />{{ t.providers.vision }}</label>
            </div>
            <div>
              <label class="block text-sm mb-1">{{ t.providers.tokens }}</label>
              <input v-model.number="drafts[provider.id].max_tokens" type="number" class="input" :placeholder="t.providers.tokensPh" />
            </div>
            <button type="button" class="btn-primary w-full" :disabled="savingId === provider.id" @click="saveCaps(provider.id)">
              {{ savingId === provider.id ? t.common.saving : t.providers.saveModel }}
            </button>
          </div>
        </div>
      </div>

      <div>
        <div class="flex items-center justify-between mb-2">
          <h2 class="text-xl font-bold text-gray-900 dark:text-white">{{ t.providers.mcpTitle }}</h2>
          <button type="button" class="btn-primary" @click="showAdd = !showAdd">{{ t.providers.mcpAdd }}</button>
        </div>
        <p class="text-sm text-gray-500 mb-4">{{ t.providers.mcpSub }}</p>

        <div v-if="showAdd" class="card mb-4 space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <input v-model="mcpForm.id" class="input" :placeholder="t.providers.mcpId" />
            <input v-model="mcpForm.name" class="input" :placeholder="t.providers.mcpName" />
            <select v-model="mcpForm.transport" class="input">
              <option value="stdio">stdio</option>
              <option value="http">http</option>
              <option value="sse">sse</option>
            </select>
            <input v-model="mcpForm.bind_models" class="input" :placeholder="t.providers.mcpBindPh" />
            <input v-if="mcpForm.transport !== 'stdio'" v-model="mcpForm.url" class="input col-span-2" :placeholder="t.providers.mcpUrl" />
            <template v-else>
              <input v-model="mcpForm.command" class="input" :placeholder="t.providers.mcpCommand" />
              <input v-model="mcpForm.args" class="input" :placeholder="t.providers.mcpArgs" />
            </template>
          </div>
          <button type="button" class="btn-primary" :disabled="savingId === 'add-mcp'" @click="submitMcp">{{ t.common.save }}</button>
        </div>

        <div v-if="mcpServers.length === 0" class="card text-sm text-gray-500">{{ t.providers.mcpEmpty }}</div>
        <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div v-for="server in mcpServers" :key="server.id" class="card">
            <div class="flex items-start justify-between">
              <div>
                <h3 class="font-semibold">{{ server.name || server.id }}</h3>
                <p class="text-sm text-gray-500 mt-1">{{ server.transport }} · {{ server.ok ? t.common.online : t.common.offline }} · {{ server.hint }}</p>
              </div>
              <span :class="server.enabled ? 'badge-info' : 'badge-warning'">{{ server.enabled ? t.common.on : t.common.off }}</span>
            </div>
            <p class="text-xs text-gray-500 mt-3" v-if="server.tools?.length">{{ t.providers.tools }}: {{ server.tools.map(x => x.name).join(', ') }}</p>
            <label class="block text-sm mt-4 mb-1">{{ t.providers.mcpBind }}</label>
            <input v-model="mcpDrafts[server.id]" class="input" :placeholder="t.providers.mcpBindPh" />
            <div class="flex gap-2 mt-3">
              <button type="button" class="btn-primary flex-1" :disabled="savingId === server.id" @click="saveBind(server.id)">{{ t.providers.mcpSave }}</button>
              <button type="button" class="btn-ghost text-red-600" @click="removeMcp(server.id)">{{ t.common.delete }}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
