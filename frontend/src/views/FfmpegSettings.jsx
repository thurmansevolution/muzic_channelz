import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAdminState, saveAdminState, stopService, startService } from '../api'

const defaultSettings = () => ({
  ffmpeg_path: '',
  ffprobe_path: '',
  hls_time: 2,
  hls_list_size: 4,
  hls_segmenter_idle_timeout_seconds: 0,
})

export default function FfmpegSettings() {
  const navigate = useNavigate()
  const [state, setState] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveNotify, setSaveNotify] = useState(null)
  const [form, setForm] = useState(defaultSettings())

  useEffect(() => {
    getAdminState().then((s) => {
      setState(s)
      const fs = s?.ffmpeg_settings
      setForm({
        ffmpeg_path: fs?.ffmpeg_path ?? '',
        ffprobe_path: fs?.ffprobe_path ?? '',
        hls_time: Math.max(1, Math.min(30, fs?.hls_time ?? 2)),
        hls_list_size: Math.max(2, Math.min(30, fs?.hls_list_size ?? 4)),
        hls_segmenter_idle_timeout_seconds: Math.max(0, fs?.hls_segmenter_idle_timeout_seconds ?? 0),
      })
    }).catch(() => setForm(defaultSettings()))
  }, [])

  const [restartOverlay, setRestartOverlay] = useState(false)

  const save = async () => {
    if (!state) return
    if (!window.confirm('Save FFmpeg settings and restart the streaming service so changes take effect?')) return
    setSaving(true)
    setSaveNotify(null)
    setRestartOverlay(true)
    try {
      const next = {
        ...state,
        ffmpeg_settings: {
          ffmpeg_path: (form.ffmpeg_path || '').trim(),
          ffprobe_path: (form.ffprobe_path || '').trim(),
          hls_time: form.hls_time,
          hls_list_size: form.hls_list_size,
          hls_segmenter_idle_timeout_seconds: form.hls_segmenter_idle_timeout_seconds,
        },
      }
      await saveAdminState(next)
      setState(next)
      try {
        await stopService()
        await startService()
        const updated = await getAdminState()
        setState(updated)
        const fs = updated?.ffmpeg_settings
        setForm((f) => ({
          ...f,
          ffmpeg_path: fs?.ffmpeg_path ?? '',
          ffprobe_path: fs?.ffprobe_path ?? '',
          hls_time: Math.max(1, Math.min(30, fs?.hls_time ?? 2)),
          hls_list_size: Math.max(2, Math.min(30, fs?.hls_list_size ?? 4)),
          hls_segmenter_idle_timeout_seconds: Math.max(0, fs?.hls_segmenter_idle_timeout_seconds ?? 0),
        }))
        setSaveNotify('Settings saved and service restarted.')
      } catch (restartErr) {
        console.error(restartErr)
        setSaveNotify('Settings saved but service restart failed.')
      }
      setTimeout(() => setSaveNotify(null), 5000)
    } catch (e) {
      console.error(e)
      setSaveNotify('Save failed.')
      setTimeout(() => setSaveNotify(null), 5000)
    } finally {
      setSaving(false)
      setRestartOverlay(false)
    }
  }

  return (
    <>
      {restartOverlay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="rounded-xl border border-surface-500 bg-surface-800 px-8 py-6 text-center shadow-xl">
            <p className="text-lg font-medium text-white">Please wait while the service restarts…</p>
          </div>
        </div>
      )}
    <div className="p-6 max-w-2xl">
      <button
        type="button"
        onClick={() => navigate('/administration')}
        className="text-slate-400 hover:text-white text-sm mb-4"
      >
        ← Back to administration
      </button>
      <h1 className="text-2xl font-semibold text-white mb-2">FFmpeg settings</h1>
      <p className="text-slate-400 text-sm mb-6">
        Global FFmpeg and HLS options.
      </p>

      <section className="rounded-xl border border-surface-500 bg-surface-700/50 p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">FFmpeg path</label>
          <input
            type="text"
            value={form.ffmpeg_path}
            onChange={(e) => setForm((f) => ({ ...f, ffmpeg_path: e.target.value }))}
            placeholder="e.g. /usr/bin/ffmpeg or leave empty for default"
            className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
          />
          <p className="text-xs text-slate-500 mt-1">Full path to the ffmpeg executable. Empty = use system default.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">FFprobe path</label>
          <input
            type="text"
            value={form.ffprobe_path}
            onChange={(e) => setForm((f) => ({ ...f, ffprobe_path: e.target.value }))}
            placeholder="e.g. /usr/bin/ffprobe or leave empty"
            className="w-full px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white placeholder-slate-500"
          />
          <p className="text-xs text-slate-500 mt-1">Optional; used if the app needs to probe media.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">HLS segment duration (seconds)</label>
          <input
            type="number"
            min={1}
            max={30}
            value={form.hls_time}
            onChange={(e) => setForm((f) => ({ ...f, hls_time: Math.max(1, Math.min(30, parseInt(e.target.value, 10) || 2)) }))}
            className="w-24 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
          />
          <p className="text-xs text-slate-500 mt-1">Length of each HLS segment in seconds (1–30). Default 2.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">HLS playlist size</label>
          <input
            type="number"
            min={2}
            max={30}
            value={form.hls_list_size}
            onChange={(e) => setForm((f) => ({ ...f, hls_list_size: Math.max(2, Math.min(30, parseInt(e.target.value, 10) || 4)) }))}
            className="w-24 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
          />
          <p className="text-xs text-slate-500 mt-1">Number of segments in the playlist (2–30). Default 4.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">HLS segmenter idle timeout (seconds)</label>
          <input
            type="number"
            min={0}
            value={form.hls_segmenter_idle_timeout_seconds}
            onChange={(e) => setForm((f) => ({ ...f, hls_segmenter_idle_timeout_seconds: Math.max(0, parseInt(e.target.value, 10) || 0) }))}
            className="w-24 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white"
          />
          <p className="text-xs text-slate-500 mt-1">0 = disabled. Optional timeout after no client requests.</p>
        </div>
        {saveNotify && <p className="text-sm text-accent-400">{saveNotify}</p>}
        <div className="flex gap-3 pt-2">
          <button
            type="button"
            onClick={save}
            disabled={saving || !state}
            className="px-4 py-2 rounded-lg bg-accent-500 text-white font-medium hover:bg-accent-400 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save settings'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/administration')}
            className="px-4 py-2 rounded-lg border border-surface-500 text-slate-300 font-medium hover:bg-surface-600"
          >
            Cancel
          </button>
        </div>
      </section>
    </div>
    </>
  )
}
