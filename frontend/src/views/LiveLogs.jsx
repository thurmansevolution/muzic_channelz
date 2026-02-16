import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getChannels, getLogContent, getAppLogContent, clearAppLog } from '../api'

const APP_LOG_ID = 'app'

export default function LiveLogs() {
  const { channelId } = useParams()
  const navigate = useNavigate()
  const [channels, setChannels] = useState([])
  const [log, setLog] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  const fetchLog = useCallback(() => {
    if (!channelId) {
      setLog('')
      return
    }
    setLoading(true)
    const fetcher = channelId === APP_LOG_ID ? getAppLogContent(500) : getLogContent(channelId, 300)
    fetcher
      .then((text) => {
        setLog(text)
        setLoading(false)
      })
      .catch(() => {
        setLog('# Failed to load log')
        setLoading(false)
      })
  }, [channelId])

  useEffect(() => {
    getChannels().then(setChannels).catch(() => setChannels([]))
  }, [])

  useEffect(() => {
    fetchLog()
  }, [fetchLog])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log])

  const selectedChannel = channelId === APP_LOG_ID ? null : channels.find((c) => c.id === channelId)

  const handleCopyToClipboard = async () => {
    if (!log) return
    try {
      await navigator.clipboard.writeText(log)
      alert('Log copied to clipboard!')
    } catch (err) {
      console.error('Failed to copy:', err)
      alert('Failed to copy to clipboard')
    }
  }

  const handleClearAppLog = async () => {
    if (channelId !== APP_LOG_ID) return
    if (!window.confirm('Clear the application log? This cannot be undone.')) return
    try {
      await clearAppLog()
      setLog('')
      fetchLog()
    } catch (e) {
      console.error(e)
      alert('Failed to clear log')
    }
  }

  const handleExportToTxt = () => {
    if (!log) return
    const blob = new Blob([log], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const name = channelId === APP_LOG_ID ? 'app-log' : `ffmpeg-log-${selectedChannel?.name || selectedChannel?.id || channelId}`
    a.download = `${name}-${new Date().toISOString().slice(0, 10)}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="p-6 flex flex-col h-full">
      <h1 className="text-2xl font-semibold text-white mb-2">live logs</h1>
      <p className="text-slate-400 text-sm mb-4">
        Select a channel to view its FFmpeg debug output. Start the service in Administration first.
      </p>

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="w-56 shrink-0 border border-surface-500 rounded-lg overflow-hidden bg-surface-700/30">
          <div className="p-2 border-b border-surface-500 text-xs text-slate-400 uppercase tracking-wider">
            Channels
          </div>
          <ul className="overflow-y-auto max-h-96">
            <li>
              <button
                type="button"
                onClick={() => navigate('/live-logs/app')}
                className={`w-full text-left px-4 py-2.5 border-b border-surface-500/50 text-sm ${
                  channelId === APP_LOG_ID ? 'bg-accent-500/20 text-accent-400' : 'text-slate-300 hover:bg-surface-600'
                }`}
              >
                Application log
              </button>
            </li>
            {channels.map((ch) => (
              <li key={ch.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/live-logs/${ch.id}`)}
                  className={`w-full text-left px-4 py-2.5 border-b border-surface-500/50 text-sm ${
                    channelId === ch.id ? 'bg-accent-500/20 text-accent-400' : 'text-slate-300 hover:bg-surface-600'
                  }`}
                >
                  {ch.name || ch.slug || ch.id}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex-1 flex flex-col min-w-0 rounded-xl border border-surface-500 bg-surface-700/50 overflow-hidden">
          <div className="p-2 border-b border-surface-500 flex items-center justify-between flex-wrap gap-2">
            <span className="text-sm text-slate-400">
              {channelId === APP_LOG_ID
                ? 'Application log'
                : selectedChannel
                  ? `FFmpeg log: ${selectedChannel.name || selectedChannel.id}`
                  : 'Select a channel'}
            </span>
            {channelId && (
              <div className="flex gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={fetchLog}
                  disabled={loading}
                  className="px-3 py-1 text-xs rounded border border-surface-500 text-slate-300 hover:bg-surface-600 font-medium disabled:opacity-50"
                >
                  Refresh
                </button>
                {channelId === APP_LOG_ID && (
                  <button
                    type="button"
                    onClick={handleClearAppLog}
                    className="px-3 py-1 text-xs rounded border border-red-500/80 text-red-400 hover:bg-red-500/20 font-medium"
                  >
                    Clear Log
                  </button>
                )}
                {log && (
                  <>
                    <button
                      type="button"
                      onClick={handleCopyToClipboard}
                      className="px-3 py-1 text-xs rounded border border-surface-500 text-slate-300 hover:bg-surface-600 font-medium"
                    >
                      Copy to Clipboard
                    </button>
                    <button
                      type="button"
                      onClick={handleExportToTxt}
                      className="px-3 py-1 text-xs rounded border border-surface-500 text-slate-300 hover:bg-surface-600 font-medium"
                    >
                      Export to .txt
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          <pre className="flex-1 p-4 overflow-auto text-xs text-slate-300 font-mono whitespace-pre-wrap break-all bg-black/30">
            {loading ? 'Loading…' : log || '# No log content yet.'}
            <span ref={bottomRef} />
          </pre>
        </div>
      </div>
    </div>
  )
}
