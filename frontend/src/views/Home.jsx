import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSystemStats } from '../api'

const SECTION_CARDS = [
  {
    id: 'channelz',
    path: '/channelz',
    label: 'channelz',
    description: 'View and control your music channels. Start or stop each channel, view the live feed, change backgrounds, and download M3U or ErsatzTV YML.',
    icon: '📺',
  },
  {
    id: 'administration',
    path: '/administration',
    label: 'administration',
    description: 'Create and bind channels to Azuracast stations, create FFmpeg profiles, and specify metadata providers. Backup/Restore muzic channelz.',
    icon: '⚙',
  },
  {
    id: 'background-editor',
    path: '/background-editor',
    label: 'background editor',
    description: 'Import channel backgrounds and adjust overlay layout. Set positions for channel name, song title, artist, artist bio, and artist image.',
    icon: '🖼',
  },
  {
    id: 'live-logs',
    path: '/live-logs',
    label: 'live logs',
    description: 'Monitor FFmpeg and metadata logs per channel. Use this to troubleshoot streaming issues or verify artist art and now-playing updates.',
    icon: '📋',
  },
  {
    id: 'documentation',
    path: '/documentation',
    label: 'documentation',
    description: 'Setup and usage guide. Step-by-step instructions on how to get started.',
    icon: '📖',
  },
]

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export default function Home() {
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)

  useEffect(() => {
    const load = () => {
      getSystemStats()
        .then(setStats)
        .catch(() => setStats(null))
    }
    load()
    const interval = setInterval(load, 3000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-full flex flex-col">
      {/* Hero area with stock-background–style gradient and subtle pattern */}
      <div
        className="flex-shrink-0 rounded-b-2xl overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #0d1117 0%, #161b22 40%, #21262d 70%, #161b22 100%)',
          boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.06)',
        }}
      >
        <div className="relative px-6 py-10 sm:py-14">
          <div className="absolute inset-0 opacity-[0.22]" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.12) 1px, transparent 0)', backgroundSize: '24px 24px' }} />
          <div className="relative">
            <h1 className="text-3xl sm:text-4xl font-bold text-white tracking-tight">muzic channelz</h1>
            <p className="mt-2 text-slate-400 text-sm sm:text-base max-w-xl">
              Create and stream live music channels from an Azuracast server to ErsatzTV (or any IPTV server that uses m3u files for streaming).
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6 space-y-8">
        {/* Section links */}
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4">Sections</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {SECTION_CARDS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => navigate(s.path)}
                className="group text-left rounded-xl border border-surface-500 bg-surface-700/80 hover:bg-surface-600 hover:border-accent-500/50 p-5 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-500"
              >
                <div className="flex items-start gap-4">
                  <span className="text-3xl opacity-90 group-hover:opacity-100">{s.icon}</span>
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-white group-hover:text-accent-400">{s.label}</h3>
                    <p className="mt-1 text-sm text-slate-400 leading-snug">{s.description}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* System resources + app usage */}
        <section className="rounded-xl border border-surface-500 bg-surface-700/50 p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4">System resources</h2>
          {stats?.error ? (
            <p className="text-slate-500 text-sm">{stats.error}</p>
          ) : stats ? (
            <div className="grid gap-8 sm:grid-cols-2 max-w-3xl">
              <div className="space-y-5">
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">System Usage</p>
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-slate-400">CPU</span>
                    <span className="text-white font-medium">
                      {stats.cpu_percent != null ? `${stats.cpu_percent}%` : '—'} of {stats.cpu_count} core{stats.cpu_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-surface-600 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all duration-500"
                      style={{ width: `${Math.min(100, stats.cpu_percent ?? 0)}%` }}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-slate-400">Memory</span>
                    <span className="text-white font-medium">
                      {formatBytes(stats.memory_used_bytes)} / {formatBytes(stats.memory_total_bytes)}
                      {stats.memory_percent != null ? ` (${stats.memory_percent}%)` : ''}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-surface-600 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all duration-500"
                      style={{ width: `${Math.min(100, stats.memory_percent ?? 0)}%` }}
                    />
                  </div>
                </div>
              </div>
              <div className="space-y-5">
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">muzic channelz Usage</p>
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-slate-400">CPU</span>
                    <span className="text-white font-medium">
                      {stats.app_cpu_percent != null && stats.cpu_count
                        ? `${Math.min(100, (stats.app_cpu_percent / stats.cpu_count)).toFixed(1)}%`
                        : '—'}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-surface-600 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all duration-500"
                      style={{
                        width: `${Math.min(100, stats.cpu_count ? (stats.app_cpu_percent ?? 0) / stats.cpu_count : 0)}%`,
                      }}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-slate-400">Memory</span>
                    <span className="text-white font-medium">
                      {formatBytes(stats.app_memory_bytes ?? 0)}
                      {stats.memory_total_bytes ? ` (${(((stats.app_memory_bytes ?? 0) / stats.memory_total_bytes) * 100).toFixed(1)}%)` : ''}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-surface-600 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all duration-500"
                      style={{
                        width: stats.memory_total_bytes
                          ? `${Math.min(100, ((stats.app_memory_bytes ?? 0) / stats.memory_total_bytes) * 100)}%`
                          : '0%',
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">Loading…</p>
          )}
        </section>
      </div>
    </div>
  )
}
