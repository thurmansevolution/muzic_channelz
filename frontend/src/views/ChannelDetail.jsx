import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Hls from 'hls.js'
import {
  getChannels,
  getM3uUrl,
  getErsatzTvYmlUrl,
  getBackgrounds,
  getStreamUrl,
  getChannelLogoUrl,
  uploadChannelLogo,
  removeChannelLogo,
  startChannel,
  stopChannel,
  restartChannel,
  updateChannel,
} from '../api'

export default function ChannelDetail() {
  const { channelId } = useParams()
  const navigate = useNavigate()
  const [channel, setChannel] = useState(null)
  const [backgrounds, setBackgrounds] = useState([])
  const [actionLoading, setActionLoading] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const [showPlayOverlay, setShowPlayOverlay] = useState(true)
  const [showBufferingOverlay, setShowBufferingOverlay] = useState(false)
  const [backgroundChangeMessage, setBackgroundChangeMessage] = useState(null)
  const [logoUploading, setLogoUploading] = useState(false)
  const [logoRemoving, setLogoRemoving] = useState(false)
  const [logoUpdated, setLogoUpdated] = useState(0)
  const videoRef = useRef(null)
  const hlsRef = useRef(null)

  useEffect(() => {
    const load = () => {
      getChannels().then((list) => {
        const ch = list.find((c) => c.id === channelId)
        setChannel(ch || null)
      })
    }
    load()
    getBackgrounds().then(setBackgrounds).catch(() => setBackgrounds([]))
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [channelId])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !channel?.is_running || !channelId) return
    setShowPlayOverlay(true)
    const t = streamKey || Date.now()
    const url = getStreamUrl(channelId) + `?t=${t}`
    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        liveSyncDurationCount: 3,
        liveMaxLatencyDurationCount: 10,
        xhrSetup(xhr) {
          xhr.setRequestHeader('Cache-Control', 'no-cache')
          xhr.setRequestHeader('Pragma', 'no-cache')
        },
      })
      hlsRef.current = hls
      hls.loadSource(url)
      hls.attachMedia(video)
      const onPlaying = () => {
        setShowPlayOverlay(false)
        setShowBufferingOverlay(false)
      }
      const onWaiting = () => {
        if (!video.paused || video.readyState >= 2) setShowBufferingOverlay(true)
      }
      const onPause = () => setShowPlayOverlay(true)
      video.addEventListener('playing', onPlaying, { once: true })
      video.addEventListener('waiting', onWaiting)
      video.addEventListener('pause', onPause)
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad()
              break
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError()
              break
            default:
              hls.destroy()
              break
          }
        }
      })
      return () => {
        video.removeEventListener('pause', onPause)
        video.removeEventListener('waiting', onWaiting)
        hls.destroy()
        hlsRef.current = null
      }
    }
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      const onPlaying = () => setShowBufferingOverlay(false)
      const onWaiting = () => { if (!video.paused || video.readyState >= 2) setShowBufferingOverlay(true) }
      const onPause = () => setShowPlayOverlay(true)
      video.addEventListener('playing', onPlaying, { once: true })
      video.addEventListener('waiting', onWaiting)
      video.addEventListener('pause', onPause)
      video.src = url
      return () => {
        video.removeEventListener('pause', onPause)
        video.removeEventListener('waiting', onWaiting)
        video.src = ''
      }
    }
  }, [channelId, channel?.is_running, streamKey])

  if (!channel) {
    return (
      <div className="p-6">
        <button type="button" onClick={() => navigate('/channelz')} className="text-accent-400 hover:underline mb-4">
          ← Back to channelz
        </button>
        <p className="text-slate-400">Channel not found.</p>
      </div>
    )
  }

  const m3uUrl = getM3uUrl(channelId)
  const ymlUrl = getErsatzTvYmlUrl(channelId)

  const runChannelAction = async (fn, opts = {}) => {
    const { bumpStreamKey = false, onError } = opts
    setActionLoading(true)
    try {
      await fn()
      const list = await getChannels()
      const ch = list.find((c) => c.id === channelId)
      if (ch) setChannel(ch)
      if (bumpStreamKey) setStreamKey(Date.now())
    } catch (e) {
      console.error(e)
      onError?.()
    } finally {
      setActionLoading(false)
    }
  }

  const handleStart = () => {
    if (!window.confirm('Start this channel\'s FFmpeg stream?')) return
    runChannelAction(() => startChannel(channelId))
  }
  const handleStop = () => {
    if (!window.confirm('Stop this channel\'s FFmpeg stream? Playback will stop.')) return
    runChannelAction(() => stopChannel(channelId))
  }
  const handleRestart = async () => {
    if (!window.confirm('Restart this channel\'s FFmpeg stream? The stream will briefly disconnect.')) return
    setShowBufferingOverlay(false)
    setShowPlayOverlay(true)
    await runChannelAction(() => restartChannel(channelId), { bumpStreamKey: true })
  }

  const displayName = channel ? (channel.name || channel.station_name || channel.slug || channel.id) : ''

  const handleBackgroundChange = async (bgId) => {
    if (bgId === (channel && channel.background_id)) return
    if (!window.confirm('Changing the background will restart the FFmpeg service for this channel. Continue?')) return
    try {
      setBackgroundChangeMessage(channel && channel.is_running ? 'Restarting channel to apply new background…' : null)
      const updated = await updateChannel(channelId, { background_id: bgId })
      setChannel(updated)
      if (channel && channel.is_running) {
        setBackgroundChangeMessage('Channel restarted.')
        setTimeout(() => setBackgroundChangeMessage(null), 5000)
      } else {
        setBackgroundChangeMessage(null)
      }
    } catch (e) {
      console.error(e)
      setBackgroundChangeMessage(null)
    }
  }

  return (
    <div className="p-6 max-w-4xl">
      <button
        type="button"
        onClick={() => navigate('/channelz')}
        className="text-accent-400 hover:underline mb-6"
      >
        ← Back to channelz
      </button>
      <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-2xl font-semibold text-white truncate">{displayName}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleStart}
            disabled={actionLoading || channel.is_running}
            className="px-4 py-2 rounded-lg border border-green-600 text-green-400 text-sm font-medium hover:bg-green-600/20 disabled:opacity-50"
          >
            {actionLoading ? '…' : 'Start channel'}
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={actionLoading || !channel.is_running}
            className="px-4 py-2 rounded-lg border border-red-600/80 text-red-400 text-sm font-medium hover:bg-red-600/20 disabled:opacity-50"
          >
            {actionLoading ? '…' : 'Stop channel'}
          </button>
          <button
            type="button"
            onClick={handleRestart}
            disabled={actionLoading || !channel.is_running}
            className="px-4 py-2 rounded-lg border border-surface-500 text-slate-200 text-sm font-medium hover:bg-surface-600 disabled:opacity-50"
          >
            {actionLoading ? '…' : 'Restart channel'}
          </button>
        </div>
      </div>

      <div className="space-y-6">
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider">Live Feed</h2>
        <section className="rounded-xl border border-surface-500 bg-surface-700/50 overflow-hidden">
          <div className="aspect-video bg-black flex items-center justify-center text-slate-500 relative">
            {channel.is_running ? (
              <>
                <video
                  key={streamKey}
                  ref={videoRef}
                  className="w-full h-full object-contain"
                  playsInline
                  muted={false}
                  controls
                />
                {showPlayOverlay && (
                  <button
                    type="button"
                    onClick={() => { videoRef.current?.play(); setShowPlayOverlay(false) }}
                    className="absolute inset-0 flex items-center justify-center bg-black/40 hover:bg-black/50 transition-colors focus:outline-none focus:ring-2 focus:ring-accent-500"
                    aria-label="Play"
                  >
                    <span className="w-20 h-20 rounded-full bg-white/90 flex items-center justify-center text-black shadow-xl">
                      <svg className="w-10 h-10 ml-1" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M8 5v14l11-7L8 5z" />
                      </svg>
                    </span>
                  </button>
                )}
                {showBufferingOverlay && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/60 text-white pointer-events-none">
                    <p className="text-sm">Buffering… Stream will resume when ready.</p>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center">
                <p className="text-lg">Live stream</p>
                <p className="text-sm mt-1">Start the service in Administration to view.</p>
              </div>
            )}
          </div>
        </section>

        {/* Background */}
        <section>
          <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">Background</h2>
          {backgroundChangeMessage && (
            <p className="text-sm text-accent-400 mb-2">{backgroundChangeMessage}</p>
          )}
          <div className="flex flex-wrap gap-2">
            {backgrounds.map((bg) => (
              <button
                key={bg.id}
                type="button"
                onClick={() => handleBackgroundChange(bg.id)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${
                  channel.background_id === bg.id
                    ? 'border-accent-500 bg-accent-500/20 text-accent-400'
                    : 'border-surface-500 text-slate-300 hover:border-surface-400'
                }`}
              >
                {bg.name}
              </button>
            ))}
          </div>
        </section>

        {/* Downloads */}
        <section>
          <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">Downloads</h2>
          <div className="flex gap-3">
            <a
              href={m3uUrl}
              download={`${channel.slug || channel.id}.m3u`}
              className="px-4 py-2 rounded-lg bg-accent-500 text-white font-medium hover:bg-accent-400 transition-colors"
            >
              Download M3U
            </a>
            <a
              href={ymlUrl}
              download={`ersatztv-${channel.slug || channel.id}.yml`}
              className="px-4 py-2 rounded-lg border border-surface-500 text-slate-300 font-medium hover:bg-surface-600 transition-colors"
            >
              Download ErsatzTV YML
            </a>
          </div>
        </section>

        {/* FFmpeg profile + Channel logo */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">FFmpeg profile</h2>
            <p className="text-white">{channel.ffmpeg_profile_name ?? channel.ffmpeg_profile_id ?? 'default'}</p>
          </section>
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Channel logo</h2>
            <p className="text-slate-400 text-sm mb-2">Shown in XMLTV and program guide. No upload = stock logo is used. A channel restart is required to apply changes.</p>
            <div className="flex items-center gap-4">
              <img
                src={`${getChannelLogoUrl(channelId)}?t=${logoUpdated}`}
                alt=""
                className="w-16 h-16 object-contain rounded bg-surface-600 border border-surface-500"
              />
              <label className="px-4 py-2 rounded border border-surface-500 text-slate-300 text-sm font-medium hover:bg-surface-600 cursor-pointer">
                {logoUploading ? 'Uploading…' : 'Upload logo'}
                <input
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  disabled={logoUploading || logoRemoving}
                  onChange={async (e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (!file) return
                    setLogoUploading(true)
                    try {
                      await uploadChannelLogo(channelId, file)
                      setLogoUpdated(Date.now())
                    } catch (err) {
                      console.error(err)
                    } finally {
                      setLogoUploading(false)
                    }
                  }}
                />
              </label>
              <button
                type="button"
                disabled={logoUploading || logoRemoving}
                onClick={async () => {
                  if (!window.confirm('Remove the uploaded logo and use the stock logo?')) return
                  setLogoRemoving(true)
                  try {
                    await removeChannelLogo(channelId)
                    setLogoUpdated(Date.now())
                  } catch (err) {
                    console.error(err)
                  } finally {
                    setLogoRemoving(false)
                  }
                }}
                className="px-4 py-2 rounded border border-surface-500 text-slate-300 text-sm font-medium hover:bg-surface-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {logoRemoving ? 'Removing…' : 'Remove'}
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
