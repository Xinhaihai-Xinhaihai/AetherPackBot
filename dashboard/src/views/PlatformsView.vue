<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getPlatforms, addPlatform, startPlatform, stopPlatform, deletePlatform } from '@/services/api'
import { useI18n } from '@/i18n'

interface Platform {
  id: string
  name?: string
  type?: string
  status?: string
  running?: boolean
}

const { t } = useI18n()
const platforms = ref<Platform[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const busy = ref('')
const showAdd = ref(false)
const form = ref({ id: '', type: 'telegram', name: '', token: '' })

async function fetchPlatforms() {
  loading.value = true
  error.value = ''
  try {
    const data = await getPlatforms()
    platforms.value = data.map((item: any) => ({
      id: item.id || item.name,
      name: item.name || item.id,
      type: item.type || '',
      status: item.status,
      running: !!item.running,
    }))
  } catch {
    error.value = t.value.platforms.fail
  } finally {
    loading.value = false
  }
}

async function toggle(p: Platform) {
  busy.value = p.id
  try {
    if (p.running) {
      await stopPlatform(p.id)
      notice.value = `${p.id} ${t.value.platforms.stopped}`
    } else {
      await startPlatform(p.id)
      notice.value = `${p.id} ${t.value.platforms.started}`
    }
    await fetchPlatforms()
  } catch {
    error.value = t.value.common.fail
  } finally {
    busy.value = ''
  }
}

async function remove(p: Platform) {
  if (!confirm(p.id)) return
  busy.value = p.id
  try {
    await deletePlatform(p.id)
    notice.value = `${p.id} ${t.value.platforms.deleted}`
    await fetchPlatforms()
  } catch {
    error.value = t.value.common.fail
  } finally {
    busy.value = ''
  }
}

async function submit() {
  busy.value = 'add'
  try {
    await addPlatform({
      id: form.value.id || `${form.value.type}_${Date.now()}`,
      type: form.value.type,
      name: form.value.name || form.value.type,
      enabled: true,
      credentials: form.value.token ? { bot_token: form.value.token } : {},
    })
    showAdd.value = false
    notice.value = t.value.platforms.added
    await fetchPlatforms()
  } catch {
    error.value = t.value.common.fail
  } finally {
    busy.value = ''
  }
}

onMounted(fetchPlatforms)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t.platforms.title }}</h1>
        <p class="text-gray-500 mt-1">{{ t.platforms.sub }}</p>
      </div>
      <button type="button" class="btn-primary" @click="showAdd = !showAdd">{{ t.platforms.add }}</button>
    </div>

    <div v-if="notice" class="mb-4 p-3 rounded-lg bg-green-50 text-sm text-green-700">{{ notice }}</div>
    <div v-if="error && !loading" class="mb-4 p-3 rounded-lg bg-red-50 text-sm text-red-600">{{ error }}</div>

    <div v-if="showAdd" class="card mb-6 space-y-3">
      <div class="grid grid-cols-2 gap-3">
        <input v-model="form.id" class="input" :placeholder="t.platforms.id" />
        <select v-model="form.type" class="input">
          <option value="telegram">telegram</option>
          <option value="discord">discord</option>
        </select>
        <input v-model="form.name" class="input" :placeholder="t.platforms.name" />
        <input v-model="form.token" class="input" :placeholder="t.platforms.token" />
      </div>
      <button type="button" class="btn-primary" :disabled="busy === 'add'" @click="submit">{{ t.common.save }}</button>
    </div>

    <div v-if="loading" class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else-if="platforms.length === 0" class="card text-center py-12">
      <h3 class="text-lg font-medium">{{ t.platforms.empty }}</h3>
      <p class="text-gray-500 mt-2">{{ t.platforms.emptyHint }}</p>
      <button type="button" class="btn-primary mt-6" @click="showAdd = true">{{ t.platforms.add }}</button>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="p in platforms" :key="p.id" class="card">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="font-semibold">{{ p.name || p.id }}</h3>
            <p class="text-sm text-gray-500">{{ p.type || p.id }}</p>
          </div>
          <span :class="p.running ? 'badge-success' : 'badge-error'">{{ p.running ? t.common.running : t.common.stopped }}</span>
        </div>
        <div class="mt-4 pt-4 border-t flex justify-between">
          <button type="button" class="btn-ghost text-sm" :disabled="busy === p.id" @click="toggle(p)">
            {{ p.running ? t.common.stop : t.common.start }}
          </button>
          <button type="button" class="btn-ghost text-sm text-red-600" :disabled="busy === p.id" @click="remove(p)">{{ t.common.delete }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
