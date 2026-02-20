import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { getChannels, updateChannel } from '../api'

export default function Channelz() {
  const navigate = useNavigate()
  const [channels, setChannels] = useState([])
  const [loading, setLoading] = useState(true)
  const [guideNumbers, setGuideNumbers] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)

  useEffect(() => {
    const load = () => {
      getChannels()
        .then((list) => {
          setChannels(list)
          setGuideNumbers((prev) => {
            const next = { ...prev }
            list.forEach((ch) => {
              if (next[ch.id] === undefined) next[ch.id] = ch.guide_number ?? ''
            })
            return next
          })
        })
        .catch(() => setChannels([]))
        .finally(() => setLoading(false))
    }
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  const setGuideNumber = (channelId, value) => {
    setGuideNumbers((prev) => ({ ...prev, [channelId]: value }))
  }

  const hasChanges = useMemo(() => {
    return channels.some((ch) => {
      const current = guideNumbers[ch.id]
      const num = current === '' || current === undefined ? null : parseInt(String(current), 10)
      const resolved = (Number.isNaN(num) || num < 1) ? null : num
      return resolved !== (ch.guide_number ?? null)
    })
  }, [channels, guideNumbers])

  const handleSave = async () => {
    if (!hasChanges || saving) return
    setSaving(true)
    setSaveMessage(null)
    try {
      await Promise.all(
        channels.map((ch) => {
          const current = guideNumbers[ch.id]
          const num = current === '' || current === undefined ? null : parseInt(String(current), 10)
          const resolved = (Number.isNaN(num) || num < 1) ? null : num
          if (resolved !== (ch.guide_number ?? null)) {
            return updateChannel(ch.id, { guide_number: resolved })
          }
          return Promise.resolve()
        })
      )
      const list = await getChannels()
      setChannels(list)
      setGuideNumbers((prev) => {
        const next = { ...prev }
        list.forEach((ch) => { next[ch.id] = ch.guide_number ?? '' })
        return next
      })
      setSaveMessage('Channel numbers saved.')
      setTimeout(() => setSaveMessage(null), 4000)
    } catch {
      setSaveMessage('Failed to save.')
      setTimeout(() => setSaveMessage(null), 4000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <h1 className="text-2xl font-semibold text-white">channelz</h1>
        {channels.length > 0 && (
          <div className="flex items-center gap-3">
            {saveMessage && (
              <span className={`text-sm font-medium ${saveMessage.includes('Failed') ? 'text-red-400' : 'text-green-400'}`}>
                {saveMessage}
              </span>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={!hasChanges || saving}
              className="px-4 py-2 rounded-lg bg-accent-600 text-white font-medium hover:bg-accent-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        )}
      </div>
      {loading ? (
        <div className="text-slate-400">Loading channels…</div>
      ) : channels.length === 0 ? (
        <div className="rounded-xl border border-surface-500 bg-surface-700/50 p-8 text-center text-slate-400">
          <p className="mb-2">No channels yet.</p>
          <p className="text-sm">Add and configure channels in <strong>Administration</strong>, then start the service.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-6">
          {channels.map((ch, index) => {
            const offlineOrDisabled = !ch.enabled || !ch.is_running
            const value = guideNumbers[ch.id] !== undefined ? guideNumbers[ch.id] : (ch.guide_number ?? '')
            return (
            <div key={ch.id} className="flex flex-col items-center">
              <button
                type="button"
                onClick={() => navigate(`/channelz/${ch.id}`)}
                className="group flex flex-col items-center focus:outline-none focus:ring-2 focus:ring-accent-500 rounded-xl overflow-hidden w-full"
              >
                <div className={`relative w-full aspect-video max-w-[240px] rounded-lg bg-surface-600 border-2 transition-colors overflow-hidden shadow-lg ${offlineOrDisabled ? 'border-red-500 ring-2 ring-red-500/50' : 'border-surface-500 group-hover:border-accent-500'}`}>
                  <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-b from-surface-600 to-surface-700">
                    <span className="text-5xl opacity-80">📺</span>
                  </div>
                  <div className="absolute bottom-0 left-0 right-0 bg-black/60 py-2 px-3 text-center">
                    <span className="text-sm font-medium text-white truncate block">{ch.name || ch.station_name || ch.slug || ch.id}</span>
                  </div>
                </div>
                <span className="mt-2 text-xs text-slate-400 group-hover:text-slate-300">{offlineOrDisabled ? 'Offline or disabled' : 'View channel'}</span>
              </button>
              <div className="mt-2 flex items-center gap-2 w-full max-w-[240px]" onClick={(e) => e.stopPropagation()}>
                <span className="text-sm text-slate-400">Guide #</span>
                <input
                  type="number"
                  min={1}
                  max={9999}
                  value={value}
                  placeholder={String(800 + index)}
                  onChange={(e) => setGuideNumber(ch.id, e.target.value)}
                  className="w-20 px-2 py-1.5 rounded bg-surface-600 border border-surface-500 text-slate-300 text-base"
                />
              </div>
            </div>
          )})}
        </div>
      )}
    </div>
  )
}
