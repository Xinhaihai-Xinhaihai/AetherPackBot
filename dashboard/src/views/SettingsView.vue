<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getConfig, updateConfig } from '@/services/api'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const config = ref<Record<string, any>>({})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref('')

// Form fields
const webHost = ref('0.0.0.0')
const webPort = ref(7619)
const adminUsername = ref('aetherpackbot')
const adminPassword = ref('')
const logLevel = ref('INFO')
const agentEnabled = ref(true)

async function fetchConfig() {
  loading.value = true
  error.value = ''
  
  try {
    config.value = await getConfig()
    
    // Populate form fields
    webHost.value = config.value.web?.host || '0.0.0.0'
    webPort.value = config.value.web?.port || 7619
    adminUsername.value = config.value.web?.admin_username || 'aetherpackbot'
    logLevel.value = config.value.logging?.level || 'INFO'
    agentEnabled.value = config.value.agent?.enabled ?? true
  } catch (e) {
    error.value = t.value.settings.fail
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  error.value = ''
  success.value = ''
  
  try {
    const updates: Record<string, any> = {
      'web.host': webHost.value,
      'web.port': webPort.value,
      'web.admin_username': adminUsername.value,
      'logging.level': logLevel.value,
      'agent.enabled': agentEnabled.value,
    }
    
    if (adminPassword.value) {
      updates['web.admin_password'] = adminPassword.value
    }
    
    await updateConfig(updates)
    success.value = t.value.settings.saved
    adminPassword.value = ''
  } catch (e) {
    error.value = t.value.settings.saveFail
  } finally {
    saving.value = false
  }
}

onMounted(fetchConfig)
</script>

<template>
  <div class="p-8">
    <!-- Header -->
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t.settings.title }}</h1>
      <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t.settings.sub }}</p>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <!-- Content -->
    <div v-else class="max-w-2xl space-y-6">
      <!-- Messages -->
      <div v-if="error" class="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
        <p class="text-sm text-red-600 dark:text-red-400">{{ error }}</p>
      </div>
      
      <div v-if="success" class="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
        <p class="text-sm text-green-600 dark:text-green-400">{{ success }}</p>
      </div>

      <!-- Web Server Settings -->
      <div class="card">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">{{ t.settings.web }}</h2>
        
        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {{ t.settings.host }}
              </label>
              <input
                v-model="webHost"
                type="text"
                class="input"
                placeholder="0.0.0.0"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {{ t.settings.port }}
              </label>
              <input
                v-model.number="webPort"
                type="number"
                class="input"
                placeholder="7619"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Authentication Settings -->
      <div class="card">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">{{ t.settings.auth }}</h2>
        
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t.settings.admin }}
            </label>
            <input
              v-model="adminUsername"
              type="text"
              class="input"
              placeholder="aetherpackbot"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t.settings.newPass }}
            </label>
            <input
              v-model="adminPassword"
              type="password"
              class="input"
              :placeholder="t.settings.passKeep"
            />
            <p class="text-xs text-gray-500 mt-1">{{ t.settings.passKeep }}</p>
          </div>
        </div>
      </div>

      <!-- Logging Settings -->
      <div class="card">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">{{ t.settings.logging }}</h2>
        
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            {{ t.settings.level }}
          </label>
          <select v-model="logLevel" class="input">
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
      </div>

      <!-- Agent Settings -->
      <div class="card">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">{{ t.settings.agent }}</h2>
        
        <div class="flex items-center justify-between">
          <div>
            <p class="font-medium text-gray-900 dark:text-white">{{ t.settings.agentOn }}</p>
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ t.settings.agentHint }}</p>
          </div>
          <button
            @click="agentEnabled = !agentEnabled"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              agentEnabled ? 'bg-primary-600' : 'bg-gray-300 dark:bg-gray-600'
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                agentEnabled ? 'translate-x-6' : 'translate-x-1'
              ]"
            />
          </button>
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex justify-end">
        <button
          @click="saveConfig"
          :disabled="saving"
          class="btn-primary"
        >
          <svg v-if="saving" class="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          {{ saving ? t.common.saving : t.settings.save }}
        </button>
      </div>
    </div>
  </div>
</template>
