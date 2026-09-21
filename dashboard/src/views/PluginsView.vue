<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getPlugins, reloadPlugin, uninstallPlugin } from '@/services/api'
import { useI18n } from '@/i18n'

interface Plugin {
  name: string
  version: string
  author: string
  description: string
  status: string
  is_builtin: boolean
}

const { t } = useI18n()
const plugins = ref<Plugin[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const reloading = ref('')
const showHint = ref(false)

async function fetchPlugins() {
  loading.value = true
  error.value = ''
  try {
    plugins.value = await getPlugins()
  } catch {
    error.value = t.value.plugins.fail
  } finally {
    loading.value = false
  }
}

async function handleReload(name: string) {
  reloading.value = name
  try {
    await reloadPlugin(name)
    notice.value = `${name} ${t.value.common.ok}`
    await fetchPlugins()
  } catch {
    error.value = t.value.common.fail
  } finally {
    reloading.value = ''
  }
}

async function handleUninstall(name: string) {
  if (!confirm(name)) return
  reloading.value = name
  try {
    await uninstallPlugin(name)
    notice.value = `${name} ${t.value.plugins.uninstalled}`
    await fetchPlugins()
  } catch {
    error.value = t.value.common.fail
  } finally {
    reloading.value = ''
  }
}

onMounted(fetchPlugins)
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold">{{ t.plugins.title }}</h1>
        <p class="text-gray-500 mt-1">{{ t.plugins.sub }}</p>
      </div>
      <div class="flex gap-2">
        <button type="button" class="btn-secondary" @click="fetchPlugins">{{ t.common.refresh }}</button>
        <button type="button" class="btn-primary" @click="showHint = !showHint">{{ t.plugins.install }}</button>
      </div>
    </div>

    <div v-if="showHint" class="card mb-4 text-sm text-gray-600">{{ t.plugins.installHint }}</div>
    <div v-if="notice" class="mb-4 p-3 rounded-lg bg-green-50 text-sm text-green-700">{{ notice }}</div>
    <div v-if="error && !loading" class="mb-4 p-3 rounded-lg bg-red-50 text-sm text-red-600">{{ error }}</div>

    <div v-if="loading" class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else-if="plugins.length === 0" class="card text-center py-12">
      <h3 class="text-lg font-medium">{{ t.plugins.empty }}</h3>
      <p class="text-gray-500 mt-2">{{ t.plugins.emptyHint }}</p>
    </div>

    <div v-else class="space-y-4">
      <div v-for="plugin in plugins" :key="plugin.name" class="card">
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-2">
              <h3 class="font-semibold">{{ plugin.name }}</h3>
              <span class="text-sm text-gray-500">v{{ plugin.version }}</span>
              <span v-if="plugin.is_builtin" class="badge-info">{{ t.common.builtin }}</span>
            </div>
            <p class="text-sm text-gray-500 mt-1">{{ plugin.description || t.plugins.noDesc }}</p>
            <p class="text-xs text-gray-400 mt-1">{{ t.common.author }}: {{ plugin.author || t.common.unknown }}</p>
          </div>
          <span :class="plugin.status === 'ENABLED' || plugin.status === 'RUNNING' ? 'badge-success' : 'badge-warning'">
            {{ plugin.status === 'ENABLED' || plugin.status === 'RUNNING' ? t.common.running : t.common.loaded }}
          </span>
        </div>
        <div class="mt-4 pt-4 border-t flex justify-end gap-2">
          <button type="button" class="btn-ghost text-sm" :disabled="reloading === plugin.name" @click="handleReload(plugin.name)">{{ t.plugins.reload }}</button>
          <button v-if="!plugin.is_builtin" type="button" class="btn-ghost text-sm text-red-600" :disabled="reloading === plugin.name" @click="handleUninstall(plugin.name)">{{ t.plugins.uninstall }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
