import { useState, useEffect } from 'react'
import { getAdminState, saveAdminState, startService, stopService, exportBackup, restoreBackup, clearMetadataCache } from '../api'

const defaultStation = () => ({ name: '', base_url: '', api_key: '', station_shortcode: '' })
const defaultProfile = () => ({ name: '', preset_name: 'custom', video_codec: 'libx264', video_bitrate: '2M', preset: 'medium', pixel_format: 'yuv420p', audio_codec: 'aac', audio_bitrate: '192k', hardware_accel: false, hw_accel_type: 'none', hw_accel_device: '', extra_args: [] })

const FFMPEG_PRESETS = {
  'ultrafast': { preset: 'ultrafast', video_codec: 'libx264', video_bitrate: '3M', audio_bitrate: '192k' },
  'superfast': { preset: 'superfast', video_codec: 'libx264', video_bitrate: '2.5M', audio_bitrate: '192k' },
  'veryfast': { preset: 'veryfast', video_codec: 'libx264', video_bitrate: '2M', audio_bitrate: '192k' },
  'faster': { preset: 'faster', video_codec: 'libx264', video_bitrate: '2M', audio_bitrate: '192k' },
  'fast': { preset: 'fast', video_codec: 'libx264', video_bitrate: '2M', audio_bitrate: '192k' },
  'medium': { preset: 'medium', video_codec: 'libx264', video_bitrate: '2M', audio_bitrate: '192k' },
  'slow': { preset: 'slow', video_codec: 'libx264', video_bitrate: '1.5M', audio_bitrate: '192k' },
  'slower': { preset: 'slower', video_codec: 'libx264', video_bitrate: '1.5M', audio_bitrate: '192k' },
  'veryslow': { preset: 'veryslow', video_codec: 'libx264', video_bitrate: '1M', audio_bitrate: '192k' },
  'custom': { preset: 'medium', video_codec: 'libx264', video_bitrate: '2M', audio_bitrate: '192k' },
}
const defaultChannel = () => ({ id: crypto.randomUUID?.() ?? `ch_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`, name: '', slug: '', azuracast_station_id: '', ffmpeg_profile_id: '', background_id: 'stock', stream_port: 0, enabled: true, extra: {} })

export default function Administration() {
  const [state, setState] = useState(null)
  const [saving, setSaving] = useState(false)
  const [serviceAction, setServiceAction] = useState(null)
  const [backupAction, setBackupAction] = useState(null)
  const [restoreError, setRestoreError] = useState(null)

  useEffect(() => {
    getAdminState().then(setState).catch(() => setState({
      azuracast_stations: [],
      metadata_providers: [],
      ffmpeg_profiles: [],
      channels: [],
      service_started: false,
    }))
  }, [])

  const update = (fn) => setState((s) => (s ? fn(s) : s))
  const [saveNotify, setSaveNotify] = useState(null)
  const [cacheNotify, setCacheNotify] = useState(null)

  const save = async () => {
    if (!state) return
    if (
      !window.confirm(
        'Save all settings and restart the streaming service? (The service will be stopped and started so changes take effect.)',
      )
    )
      return
    setSaving(true)
    setSaveNotify(null)
    try {
      const next = await saveAdminState(state)
      setState(next)
      if (next?.service_started) {
        try {
          await stopService()
          await startService()
          await getAdminState().then(setState)
          setSaveNotify('Settings saved and service restarted.')
          window.alert('Settings saved. Service restarted successfully.')
        } catch (restartErr) {
          console.error(restartErr)
          setSaveNotify('Settings saved but restart failed.')
          window.alert('Restart failed. Settings were saved but the streaming service could not be restarted.')
        }
      } else {
        setSaveNotify('Settings saved.')
        window.alert('Settings saved.')
      }
      setTimeout(() => setSaveNotify(null), 5000)
    } catch (e) {
      console.error(e)
      setSaveNotify('Save or restart failed.')
      window.alert('Save or restart failed.')
      setTimeout(() => setSaveNotify(null), 5000)
    } finally {
      setSaving(false)
    }
  }

  const handleStart = async () => {
    if (!window.confirm('Start the FFmpeg service? All enabled channels will begin streaming.')) return
    setServiceAction('starting')
    try {
      const res = await startService()
      const next = await getAdminState()
      setState(next)
      if (!res?.ok && res?.message) {
        window.alert(res.message)
        return
      }
      if (res?.channels && Object.keys(res.channels).length > 0) {
        const failed = Object.entries(res.channels).filter(([, v]) => v !== 'ok')
        if (failed.length > 0 && !next?.service_started) {
          const details = failed.map(([id, err]) => `${id}: ${err}`).join('\n')
          window.alert(
            (res.message || 'Service could not stay started.') +
              '\n\nDetails:\n' + details +
              '\n\nCheck Live logs for FFmpeg errors.'
          )
        } else if (failed.length > 0 && next?.service_started) {
          window.alert(`Started with some failures:\n${failed.map(([id, err]) => `${id}: ${err}`).join('\n')}`)
        }
      } else if (res?.message && !next?.service_started) {
        window.alert(res.message)
      }
    } catch (e) {
      console.error(e)
      window.alert(e?.message || 'Failed to start service.')
    } finally {
      setServiceAction(null)
    }
  }

  const handleStop = async () => {
    if (!window.confirm('Stop the FFmpeg service? All channel streams will stop.')) return
    setServiceAction('stopping')
    try {
      await stopService()
      await getAdminState().then(setState)
    } finally {
      setServiceAction(null)
    }
  }

  if (!state) return <div className="p-6 text-slate-400">Loading…</div>

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-2xl font-semibold text-white mb-2">administration</h1>
      <p className="text-slate-400 text-sm mb-6">Configure Azuracast, metadata providers, FFmpeg profiles, and channels. Then start the service.</p>

      {/* Service control */}
      <section className="mb-8 rounded-xl border border-surface-500 bg-surface-700/50 p-6">
        <h2 className="text-lg font-medium text-white mb-4">Service</h2>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={handleStart}
            disabled={state.service_started || serviceAction === 'starting'}
            className="px-4 py-2 rounded-lg bg-green-600 text-white font-medium hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {serviceAction === 'starting' ? 'Starting…' : 'Start service'}
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={!state.service_started || serviceAction === 'stopping'}
            className="px-4 py-2 rounded-lg border border-red-500/60 text-red-400 font-medium hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {serviceAction === 'stopping' ? 'Stopping…' : 'Stop service'}
          </button>
        </div>
        {state.service_started && <p className="mt-2 text-sm text-green-400">Service is running.</p>}
      </section>

      {/* Backup & restore */}
      <section className="mb-8 rounded-xl border border-surface-500 bg-surface-700/50 p-6">
        <h2 className="text-lg font-medium text-white mb-4">Backup & restore</h2>
        <p className="text-slate-400 text-sm mb-4">
          Export a full backup (admin state, channels, FFmpeg profiles, Azuracast stations, and custom background images) to a JSON file. Restore on a new install by uploading that file. Restore will stop the service and replace the current configuration.
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={async () => {
              if (!window.confirm('Export a full backup (configuration and custom backgrounds)?')) return
              setBackupAction('exporting')
              setRestoreError(null)
              try {
                const payload = await exportBackup(true)
                const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
                const a = document.createElement('a')
                a.href = URL.createObjectURL(blob)
                a.download = `muzic-channelz-backup-${new Date().toISOString().slice(0, 10)}.json`
                a.click()
                URL.revokeObjectURL(a.href)
              } catch (e) {
                setRestoreError(e.message)
              } finally {
                setBackupAction(null)
              }
            }}
            disabled={backupAction !== null}
            className="px-4 py-2 rounded-lg bg-accent-600 text-white font-medium hover:bg-accent-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {backupAction === 'exporting' ? 'Exporting…' : 'Export backup'}
          </button>
          <label className="px-4 py-2 rounded-lg border border-surface-500 text-slate-300 font-medium hover:bg-surface-600 cursor-pointer">
            Restore backup
            <input
              type="file"
              accept=".json,application/json"
              className="sr-only"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                setRestoreError(null)
                try {
                  const text = await file.text()
                  const payload = JSON.parse(text)
                  if (!payload.admin_state || !Array.isArray(payload.backgrounds)) {
                    setRestoreError('Invalid backup file: missing admin_state or backgrounds.')
                    return
                  }
                  if (!window.confirm('Restore will stop the service and replace all configuration and custom backgrounds. Continue?')) return
                  setBackupAction('restoring')
                  await restoreBackup({
                    admin_state: payload.admin_state,
                    backgrounds: payload.backgrounds,
                    background_images: payload.background_images || {},
                  })
                  const next = await getAdminState()
                  setState(next)
                } catch (err) {
                  setRestoreError(err.message || 'Restore failed')
                } finally {
                  setBackupAction(null)
                }
              }}
            />
          </label>
          {backupAction === 'restoring' && <span className="text-sm text-slate-400">Restoring…</span>}
        </div>
        {restoreError && <p className="mt-2 text-sm text-red-400">{restoreError}</p>}
      </section>

      {/* Azuracast stations */}
      <section className="mb-8">
        <h2 className="text-lg font-medium text-white mb-3">azuracast stations</h2>
        <p className="text-slate-400 text-sm mb-3">
          Add each Azuracast station you would like to use.
        </p>
        {(state.azuracast_stations || []).map((station, i) => (
          <div key={i} className="mb-4 p-4 rounded-lg border border-surface-500 bg-surface-700/30 space-y-2">
            <input
              placeholder="Name (e.g. My Station)"
              value={station.name}
              onChange={(e) => update((s) => ({ ...s, azuracast_stations: s.azuracast_stations.map((st, j) => (j === i ? { ...st, name: e.target.value } : st)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
            />
            <input
              placeholder="Base URL (e.g. http://192.168.1.100)"
              value={station.base_url}
              onChange={(e) => update((s) => ({ ...s, azuracast_stations: s.azuracast_stations.map((st, j) => (j === i ? { ...st, base_url: e.target.value } : st)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
            />
            <div>
              <input
                placeholder="API key (optional for public stations)"
                type="password"
                value={station.api_key}
                onChange={(e) => update((s) => ({ ...s, azuracast_stations: s.azuracast_stations.map((st, j) => (j === i ? { ...st, api_key: e.target.value } : st)) }))}
                className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
              />
              <p className="text-xs text-slate-500 mt-1">Only needed for authenticated API calls. Public stations can leave this blank.</p>
            </div>
            <div>
              <input
                placeholder="Station shortcode (e.g. my_station)"
                value={station.station_shortcode}
                onChange={(e) => update((s) => ({ ...s, azuracast_stations: s.azuracast_stations.map((st, j) => (j === i ? { ...st, station_shortcode: e.target.value } : st)) }))}
                className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
              />
              <p className="text-xs text-slate-500 mt-1">From your station’s public URL: …/public/<strong>my_station</strong> or …/listen/<strong>my_station</strong>/radio.mp3</p>
            </div>
            <button
              type="button"
              onClick={() => {
                if (!window.confirm(`Remove station "${station.name || station.station_shortcode || 'this station'}"?`)) return
                update((s) => ({ ...s, azuracast_stations: s.azuracast_stations.filter((_, j) => j !== i) }))
              }}
              className="text-sm text-red-400 hover:underline"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => update((s) => ({ ...s, azuracast_stations: [...(s.azuracast_stations || []), defaultStation()] }))}
          className="text-sm text-accent-400 hover:underline"
        >
          + Add station
        </button>
      </section>

      {/* Metadata providers */}
      <section className="mb-8">
        <h2 className="text-lg font-medium text-white mb-3">metadata providers</h2>
        <p className="text-slate-400 text-sm mb-3">
          Optional. Used to fill the <strong>Artist bio</strong>, <strong>Artist name</strong>, <strong>Artist image</strong>, and other metadata information in live channelz. <strong>Custom</strong>: use base URL and API key for your own provider.</p>
        {(state.metadata_providers || []).map((prov, i) => {
          const knownProviders = ['MusicBrainz', 'Last.fm', 'TheAudioDB', 'Discogs', 'Spotify', 'Genius', 'iTunes', 'Deezer', 'Custom']
          const isCustom = prov.name && !knownProviders.includes(prov.name)
          const isCustomOption = prov.name === 'Custom' || isCustom
          const selectedProvider = knownProviders.includes(prov.name) ? prov.name : (isCustom ? 'Custom' : prov.name || '')
          return (
          <div key={i} className="mb-4 p-4 rounded-lg border border-surface-500 bg-surface-700/30 space-y-2">
            <div className="flex gap-2">
              <select
                value={selectedProvider}
                onChange={(e) => {
                  const name = e.target.value
                  update((s) => ({ ...s, metadata_providers: s.metadata_providers.map((p, j) => (j === i ? { ...p, name } : p)) }))
                }}
                className="flex-1 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
              >
                <option value="">— Select provider —</option>
                <option value="MusicBrainz">MusicBrainz</option>
                <option value="Last.fm">Last.fm</option>
                <option value="TheAudioDB">TheAudioDB</option>
                <option value="Discogs">Discogs</option>
                <option value="Spotify">Spotify</option>
                <option value="Genius">Genius</option>
                <option value="iTunes">iTunes</option>
                <option value="Deezer">Deezer</option>
                <option value="Custom">Custom</option>
              </select>
              {(selectedProvider === 'Custom' || !selectedProvider) && (
                <input
                  placeholder={selectedProvider === 'Custom' ? 'Custom provider name' : 'Other provider name'}
                  value={selectedProvider === 'Custom' || isCustom ? (prov.name || '') : ''}
                  onChange={(e) => update((s) => ({ ...s, metadata_providers: s.metadata_providers.map((p, j) => (j === i ? { ...p, name: e.target.value } : p)) }))}
                  className="flex-1 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
                />
              )}
            </div>
            <input
              placeholder="Base URL (optional — for Custom or API override)"
              value={prov.base_url}
              onChange={(e) => update((s) => ({ ...s, metadata_providers: s.metadata_providers.map((p, j) => (j === i ? { ...p, base_url: e.target.value } : p)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            />
            <input
              placeholder="API key / token"
              type="password"
              value={prov.api_key_or_token}
              onChange={(e) => update((s) => ({ ...s, metadata_providers: s.metadata_providers.map((p, j) => (j === i ? { ...p, api_key_or_token: e.target.value } : p)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            />
            <button
              type="button"
              onClick={() => {
                if (!window.confirm(`Remove metadata provider "${prov.name || 'this provider'}"?`)) return
                update((s) => ({ ...s, metadata_providers: s.metadata_providers.filter((_, j) => j !== i) }))
              }}
              className="text-sm text-red-400 hover:underline"
            >
              Remove
            </button>
          </div>
          )
        })}
        <button
          type="button"
          onClick={() => update((s) => ({ ...s, metadata_providers: [...(s.metadata_providers || []), { name: '', api_key_or_token: '', base_url: '' }] }))}
          className="text-sm text-accent-400 hover:underline"
        >
          + Add provider
        </button>
        <div className="mt-4 pt-4 border-t border-surface-500">
          <p className="text-slate-400 text-sm mb-2">Artist metadata (bios and images) is cached locally to reduce API calls. Clear the cache to force a fresh fetch for each artist.</p>
          <button
            type="button"
            onClick={async () => {
              if (!window.confirm('Clear all cached artist metadata (bios and images)? The next play of each artist will fetch from providers again.')) return
              setCacheNotify(null)
              try {
                const res = await clearMetadataCache()
                setCacheNotify(res?.ok ? (res.message || 'Metadata cache cleared.') : (res?.message || 'Failed to clear cache.'))
              } catch (e) {
                setCacheNotify(e?.message || 'Failed to clear cache.')
              }
              setTimeout(() => setCacheNotify(null), 5000)
            }}
            className="text-sm text-amber-400 hover:underline"
          >
            Clear metadata cache
          </button>
          {cacheNotify && (
            <p className={`text-sm mt-2 ${cacheNotify.startsWith('Metadata cache cleared') ? 'text-green-400' : 'text-red-400'}`}>
              {cacheNotify}
            </p>
          )}
        </div>
      </section>

      {/* FFmpeg profiles */}
      <section className="mb-8">
        <h2 className="text-lg font-medium text-white mb-3">ffmpeg profiles</h2>
        {(state.ffmpeg_profiles || []).map((prof, i) => {
          const presetName = prof.preset_name || 'custom'
          const applyPreset = (presetKey) => {
            const preset = FFMPEG_PRESETS[presetKey] || FFMPEG_PRESETS.custom
            update((s) => ({
              ...s,
              ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) =>
                j === i
                  ? {
                      ...p,
                      preset_name: presetKey,
                      preset: preset.preset,
                      video_codec: preset.video_codec,
                      video_bitrate: preset.video_bitrate,
                      audio_bitrate: preset.audio_bitrate,
                    }
                  : p,
              ),
            }))
          }
          return (
          <div key={i} className="mb-4 p-4 rounded-lg border border-surface-500 bg-surface-700/30 space-y-3">
            <input
              placeholder="Profile name"
              value={prof.name}
              onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, name: e.target.value } : p)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            />
            <div>
              <label className="block text-xs text-slate-400 mb-1">Preset</label>
              <select
                value={presetName}
                onChange={(e) => applyPreset(e.target.value)}
                className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
              >
                <option value="ultrafast">Ultrafast (fastest, lower quality)</option>
                <option value="superfast">Superfast</option>
                <option value="veryfast">Veryfast</option>
                <option value="faster">Faster</option>
                <option value="fast">Fast</option>
                <option value="medium">Medium (balanced)</option>
                <option value="slow">Slow</option>
                <option value="slower">Slower</option>
                <option value="veryslow">Veryslow (slowest, best quality)</option>
                <option value="custom">Custom (manual settings)</option>
              </select>
            </div>
            {presetName === 'custom' && (
              <div className="grid grid-cols-2 gap-2">
                <input
                  placeholder="Video codec (e.g. libx264)"
                  value={prof.video_codec}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, video_codec: e.target.value } : p)) }))}
                  className="px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                />
                <input
                  placeholder="Video bitrate (e.g. 2M)"
                  value={prof.video_bitrate}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, video_bitrate: e.target.value } : p)) }))}
                  className="px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                />
                <input
                  placeholder="Preset (e.g. medium)"
                  value={prof.preset}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, preset: e.target.value } : p)) }))}
                  className="px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                />
                <input
                  placeholder="Audio codec (e.g. aac)"
                  value={prof.audio_codec}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, audio_codec: e.target.value } : p)) }))}
                  className="px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                />
                <input
                  placeholder="Audio bitrate (e.g. 192k)"
                  value={prof.audio_bitrate}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, audio_bitrate: e.target.value } : p)) }))}
                  className="px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                />
              </div>
            )}
            <div className="border-t border-surface-500 pt-3">
              <label className="flex items-center gap-2 text-sm text-slate-300 mb-2">
                <input
                  type="checkbox"
                  checked={prof.hardware_accel || false}
                  onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, hardware_accel: e.target.checked } : p)) }))}
                  className="rounded border-surface-500"
                />
                Enable hardware acceleration
              </label>
              {prof.hardware_accel && (
                <div className="ml-6 space-y-2 mt-2">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Hardware type</label>
                    <select
                      value={prof.hw_accel_type || 'none'}
                      onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, hw_accel_type: e.target.value } : p)) }))}
                      className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                    >
                      <option value="none">None</option>
                      <option value="nvenc">NVIDIA NVENC (NVIDIA GPU)</option>
                      <option value="vaapi">VAAPI (Intel/AMD GPU)</option>
                      <option value="qsv">Intel Quick Sync Video</option>
                      <option value="videotoolbox">VideoToolbox (macOS)</option>
                    </select>
                  </div>
                  {(prof.hw_accel_type === 'vaapi' || prof.hw_accel_type === 'qsv') && (
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Device path (optional)</label>
                      <input
                        placeholder={prof.hw_accel_type === 'vaapi' ? '/dev/dri/renderD128' : '/dev/dri/renderD128'}
                        value={prof.hw_accel_device || ''}
                        onChange={(e) => update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.map((p, j) => (j === i ? { ...p, hw_accel_device: e.target.value } : p)) }))}
                        className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                if (!window.confirm(`Remove FFmpeg profile "${prof.name || 'this profile'}"? Channels using it will need another profile.`)) return
                update((s) => ({ ...s, ffmpeg_profiles: s.ffmpeg_profiles.filter((_, j) => j !== i) }))
              }}
              className="text-sm text-red-400 hover:underline"
            >
              Remove
            </button>
          </div>
          )
        })}
        <button
          type="button"
          onClick={() => update((s) => ({ ...s, ffmpeg_profiles: [...(s.ffmpeg_profiles || []), defaultProfile()] }))}
          className="text-sm text-accent-400 hover:underline"
        >
          + Add profile
        </button>
      </section>

      {/* Channels */}
      <section className="mb-8">
        <h2 className="text-lg font-medium text-white mb-3">channelz</h2>
        <p className="text-slate-400 text-sm mb-3">
          For each channel, pair an AzuraCast station with an FFmpeg profile. Slug is optional.
        </p>
        {(state.channels || []).map((ch, i) => (
          <div key={i} className="mb-4 p-4 rounded-lg border border-surface-500 bg-surface-700/30 space-y-2">
            <input
              placeholder="Channel name"
              value={ch.name}
              onChange={(e) => update((s) => ({ ...s, channels: s.channels.map((c, j) => (j === i ? { ...c, name: e.target.value } : c)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            />
            <input
              placeholder="Slug (optional, for filenames)"
              value={ch.slug}
              onChange={(e) => update((s) => ({ ...s, channels: s.channels.map((c, j) => (j === i ? { ...c, slug: e.target.value } : c)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            />
            <select
              value={ch.azuracast_station_id}
              onChange={(e) => update((s) => ({ ...s, channels: s.channels.map((c, j) => (j === i ? { ...c, azuracast_station_id: e.target.value } : c)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            >
              <option value="">— Station —</option>
              {(state.azuracast_stations || []).map((st) => (
                <option key={st.name} value={st.name}>{st.name || st.station_shortcode || 'Unnamed'}</option>
              ))}
            </select>
            <select
              value={ch.ffmpeg_profile_id}
              onChange={(e) => update((s) => ({ ...s, channels: s.channels.map((c, j) => (j === i ? { ...c, ffmpeg_profile_id: e.target.value } : c)) }))}
              className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
            >
              <option value="">— Profile —</option>
              {(state.ffmpeg_profiles || []).map((p) => (
                <option key={p.name} value={p.name}>{p.name || 'Unnamed'}</option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={ch.enabled}
                onChange={(e) => update((s) => ({ ...s, channels: s.channels.map((c, j) => (j === i ? { ...c, enabled: e.target.checked } : c)) }))}
                className="rounded border-surface-500"
              />
              Enabled
            </label>
            <button
              type="button"
              onClick={() => {
                if (!window.confirm(`Remove channel "${ch.name || ch.slug || ch.id || 'this channel'}"? This cannot be undone until you save.`)) return
                update((s) => ({ ...s, channels: s.channels.filter((_, j) => j !== i) }))
              }}
              className="text-sm text-red-400 hover:underline"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => update((s) => ({ ...s, channels: [...(s.channels || []), defaultChannel()] }))}
          className="text-sm text-accent-400 hover:underline"
        >
          + Add channel
        </button>
      </section>

      {saveNotify && (
        <p className={`text-sm mb-3 ${saveNotify.startsWith('Save or restart failed') ? 'text-red-400' : 'text-accent-400'}`}>
          {saveNotify}
        </p>
      )}
      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="px-6 py-2.5 rounded-lg bg-accent-500 text-white font-medium hover:bg-accent-400 disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save all'}
      </button>
    </div>
  )
}
