import { computed, ref } from 'vue'
import zh from './zh'
import en from './en'

export type Locale = 'zh' | 'en'
export type Dict = typeof zh

const KEY = 'aetherpack.locale'
const dicts: Record<Locale, Dict> = { zh, en }

function readLocale(): Locale {
  const raw = localStorage.getItem(KEY)
  return raw === 'en' ? 'en' : 'zh'
}

const locale = ref<Locale>(readLocale())

export function useI18n() {
  const t = computed(() => dicts[locale.value])
  function setLocale(next: Locale) {
    locale.value = next
    localStorage.setItem(KEY, next)
  }
  return { locale, t, setLocale }
}
