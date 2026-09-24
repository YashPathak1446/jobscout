/**
 * The Gemini key, kept in this browser and nowhere else (R117).
 *
 * The server never stores it: it arrives in a POST body, is used for that
 * request or run, and is forgotten. So the browser is the only place it can
 * survive a reload, and `localStorage` is that place.
 *
 * Every read and write is guarded. Storage throws in a private window, with
 * site data blocked, or in an embedded preview, and a key page that crashed
 * there would lose the one configuration that needs no key at all. When
 * storage is unavailable the key lives in memory for this page only, and
 * `persisted: false` lets the page say so rather than promise a save it did
 * not make.
 */
const STORAGE_KEY = 'jobscout.geminiKey'

export type StoredKey = { key: string; persisted: boolean }

export function loadKey(): StoredKey {
  try {
    return { key: window.localStorage.getItem(STORAGE_KEY) ?? '', persisted: true }
  } catch {
    return { key: '', persisted: false }
  }
}

/** Whether the key was saved. An empty key is removed, not stored as ''. */
export function saveKey(key: string): boolean {
  try {
    if (key) {
      window.localStorage.setItem(STORAGE_KEY, key)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
    return true
  } catch {
    return false
  }
}

/** Whether the stored copy is gone. False only when storage refused. */
export function forgetKey(): boolean {
  return saveKey('')
}
