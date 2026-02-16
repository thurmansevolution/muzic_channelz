import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getChannels } from '../api'

export default function Channelz() {
  const navigate = useNavigate()
  const [channels, setChannels] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => {
      getChannels()
        .then(setChannels)
        .catch(() => setChannels([]))
        .finally(() => setLoading(false))
    }
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-white mb-6">channelz</h1>
      {loading ? (
        <div className="text-slate-400">Loading channels…</div>
      ) : channels.length === 0 ? (
        <div className="rounded-xl border border-surface-500 bg-surface-700/50 p-8 text-center text-slate-400">
          <p className="mb-2">No channels yet.</p>
          <p className="text-sm">Add and configure channels in <strong>Administration</strong>, then start the service.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-6">
          {channels.map((ch) => {
            const offlineOrDisabled = !ch.enabled || !ch.is_running
            return (
            <button
              key={ch.id}
              type="button"
              onClick={() => navigate(`/channelz/${ch.id}`)}
              className="group flex flex-col items-center focus:outline-none focus:ring-2 focus:ring-accent-500 rounded-xl overflow-hidden"
            >
              <div className={`relative w-full aspect-video max-w-[240px] rounded-lg bg-surface-600 border-2 transition-colors overflow-hidden shadow-lg ${offlineOrDisabled ? 'border-red-500 ring-2 ring-red-500/50' : 'border-surface-500 group-hover:border-accent-500'}`}>
                <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-b from-surface-600 to-surface-700">
                  <span className="text-5xl opacity-80">📺</span>
                </div>
                <div className="absolute bottom-0 left-0 right-0 bg-black/60 py-2 px-3 text-center">
                  <span className="text-sm font-medium text-white truncate block">{ch.name || ch.slug || ch.id}</span>
                </div>
              </div>
              <span className="mt-2 text-xs text-slate-400 group-hover:text-slate-300">{offlineOrDisabled ? 'Offline or disabled' : 'View channel'}</span>
            </button>
          )})}
        </div>
      )}
    </div>
  )
}
