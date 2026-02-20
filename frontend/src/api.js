const BASE = ''

export async function getAdminState() {
  const r = await fetch(`${BASE}/api/admin/state`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function saveAdminState(state) {
  const r = await fetch(`${BASE}/api/admin/state`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state),
  })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function startService() {
  const r = await fetch(`${BASE}/api/admin/start-service`, { method: 'POST' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data?.detail || data?.message || r.statusText)
  return data
}

export async function stopService() {
  const r = await fetch(`${BASE}/api/admin/stop-service`, { method: 'POST' })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function getChannels() {
  const r = await fetch(`${BASE}/api/channels`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function startChannel(id) {
  const r = await fetch(`${BASE}/api/channels/${id}/start`, { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function stopChannel(id) {
  const r = await fetch(`${BASE}/api/channels/${id}/stop`, { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function restartChannel(id) {
  const r = await fetch(`${BASE}/api/channels/${id}/restart`, { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function updateChannel(id, body) {
  const r = await fetch(`${BASE}/api/channels/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function getM3uUrl(channelId) {
  return `${BASE}/api/channels/${channelId}/m3u`
}

export function getPlaylistM3uUrl() {
  return `${BASE}/playlist.m3u`
}

export function getGuideXmlUrl() {
  return `${BASE}/guide.xml`
}

/** Base URL for M3U/XMLTV so other devices can use it (LAN IP or MUZIC_PUBLIC_HOST). */
export async function getPublicBaseUrl() {
  const r = await fetch(`${BASE}/api/system/public-url`)
  if (!r.ok) return null
  const data = await r.json()
  return data?.base_url ?? null
}

export function getErsatzTvYmlUrl(channelId) {
  return `${BASE}/api/channels/${channelId}/ersatztv-yml`
}

export function getStreamUrl(channelId) {
  return `${BASE}/stream/${channelId}/index.m3u8`
}

export function getChannelLogoUrl(channelId) {
  return `${BASE}/api/channels/logo/${channelId}`
}

export async function uploadChannelLogo(channelId, file) {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch(`${BASE}/api/channels/logo/${channelId}`, {
    method: 'POST',
    body: form,
  })
  if (!r.ok) throw new Error(await r.text() || r.statusText)
  return r.json()
}

export async function removeChannelLogo(channelId) {
  const r = await fetch(`${BASE}/api/channels/logo/${channelId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text() || r.statusText)
  return r.json()
}

export async function getBackgrounds() {
  const r = await fetch(`${BASE}/api/backgrounds`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function uploadBackground(file, name = '') {
  const form = new FormData()
  form.append('file', file)
  if (name) form.append('name', name)
  const r = await fetch(`${BASE}/api/backgrounds/upload`, {
    method: 'POST',
    body: form,
  })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function updateBackground(id, body) {
  const r = await fetch(`${BASE}/api/backgrounds/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function deleteBackground(id) {
  const r = await fetch(`${BASE}/api/backgrounds/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text() || r.statusText)
  return r.json()
}

export async function getLogContent(channelId, tail = 300) {
  const r = await fetch(`${BASE}/api/logs/${channelId}?tail=${tail}`)
  if (!r.ok) throw new Error(r.statusText)
  return r.text()
}

export async function getAppLogContent(tail = 500) {
  const r = await fetch(`${BASE}/api/logs/app?tail=${tail}`)
  if (!r.ok) throw new Error(r.statusText)
  return r.text()
}

export async function clearAppLog() {
  const r = await fetch(`${BASE}/api/logs/app`, { method: 'DELETE' })
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function getSystemStats() {
  const r = await fetch(`${BASE}/api/system/stats`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function exportBackup(includeImages = true) {
  const r = await fetch(`${BASE}/api/admin/backup?include_images=${includeImages}`)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export async function restoreBackup(payload) {
  const r = await fetch(`${BASE}/api/admin/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(await r.text() || r.statusText)
  return r.json()
}

export async function clearMetadataCache() {
  const r = await fetch(`${BASE}/api/admin/metadata-cache`, { method: 'DELETE' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.message || r.statusText)
  return data
}
