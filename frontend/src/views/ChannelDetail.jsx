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
  updateChannel,
  startChannel,
  stopChannel,
  getAdminState,
} from '../api'

const _pendingStops = new Map()
let _cachedIdleSeconds = 60

function _cancelPendingStop(channelId) {
  const id = _pendingStops.get(channelId)
  if (id !== undefined) {
    clearTimeout(id)
    _pendingStops.delete(channelId)
  }
}

function _schedulePendingStop(channelId) {
  const secs = _cachedIdleSeconds > 0 ? _cachedIdleSeconds * 1000 : 60000
  _cancelPendingStop(channelId)
  const id = setTimeout(() => {
    _pendingStops.delete(channelId)
    stopChannel(channelId, true).catch(() => {})
  }, secs)
  _pendingStops.set(channelId, id)
}

export default function ChannelDetail() {
  const { channelId } = useParams()
  const navigate = useNavigate()
  const [channel, setChannel] = useState(null)
  const [backgrounds, setBackgrounds] = useState([])
  const [streamKey, setStreamKey] = useState(0)
  const [showPlayOverlay, setShowPlayOverlay] = useState(true)
  const [showBufferingOverlay, setShowBufferingOverlay] = useState(false)
  const [backgroundChangeMessage, setBackgroundChangeMessage] = useState(null)
  const [logoUploading, setLogoUploading] = useState(false)
  const [logoRemoving, setLogoRemoving] = useState(false)
  const [logoUpdated, setLogoUpdated] = useState(0)
  const videoRef = useRef(null)
  const hlsRef = useRef(null)
  const wantsPlayRef = useRef(false)
  const autoPlayRef = useRef(false)

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
    getAdminState().then((s) => {
      const secs = s?.ffmpeg_settings?.channel_idle_shutdown_seconds
      if (typeof secs === 'number') _cachedIdleSeconds = secs
    }).catch(() => {})
    _cancelPendingStop(channelId)
    startChannel(channelId).catch(() => {})
    return () => {
      _schedulePendingStop(channelId)
    }
  }, [channelId])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !channelId) return
    const autoPlay = autoPlayRef.current
    autoPlayRef.current = false
    setShowPlayOverlay(!autoPlay)
    setShowBufferingOverlay(autoPlay)
    wantsPlayRef.current = autoPlay
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
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (wantsPlayRef.current) {
          video.play().catch(() => {})
        }
      })
      const onPlaying = () => {
        setShowPlayOverlay(false)
        setShowBufferingOverlay(false)
      }
      const onWaiting = () => {
        if (!video.paused) setShowBufferingOverlay(true)
      }
      const onPause = () => setShowPlayOverlay(true)
      const onNativePlay = () => {
        wantsPlayRef.current = true
        startChannel(channelId).catch(() => {})
      }
      video.addEventListener('playing', onPlaying)
      video.addEventListener('waiting', onWaiting)
      video.addEventListener('pause', onPause)
      video.addEventListener('play', onNativePlay)
      let retryTimer = null
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              if (retryTimer) clearTimeout(retryTimer)
              retryTimer = setTimeout(() => {
                hls.loadSource(url)
                hls.startLoad()
              }, 3000)
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
        if (retryTimer) clearTimeout(retryTimer)
        video.removeEventListener('playing', onPlaying)
        video.removeEventListener('waiting', onWaiting)
        video.removeEventListener('pause', onPause)
        video.removeEventListener('play', onNativePlay)
        hls.destroy()
        hlsRef.current = null
      }
    }
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      const onPlaying = () => {
        setShowPlayOverlay(false)
        setShowBufferingOverlay(false)
      }
      const onWaiting = () => {
        if (!video.paused) setShowBufferingOverlay(true)
      }
      const onPause = () => setShowPlayOverlay(true)
      video.addEventListener('playing', onPlaying)
      video.addEventListener('waiting', onWaiting)
      video.addEventListener('pause', onPause)
      video.src = url
      return () => {
        video.removeEventListener('playing', onPlaying)
        video.removeEventListener('waiting', onWaiting)
        video.removeEventListener('pause', onPause)
        video.src = ''
      }
    }
  }, [channelId, streamKey])

  const m3uUrl = getM3uUrl(channelId)
  const ymlUrl = getErsatzTvYmlUrl(channelId)

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
      {channel && (
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-white truncate">{displayName}</h1>
        </div>
      )}

      <div className="space-y-6">
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider">Live Feed</h2>
        <section className="rounded-xl border border-surface-500 bg-surface-700/50 overflow-hidden">
          <div className="aspect-video bg-black flex items-center justify-center text-slate-500 relative">
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
                onClick={() => {
                  autoPlayRef.current = true
                  startChannel(channelId).catch(() => {})
                  setStreamKey((k) => k + 1)
                }}
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
          </div>
        </section>

        {channel && <>
        {/* Row 1: Background | Downloads */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
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
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">Downloads</h2>
            <div className="flex flex-wrap gap-3">
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
        </div>

        {/* Row 2: Channel Logo | FFmpeg Profile */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Channel logo</h2>
            <p className="text-slate-400 text-sm mb-2">Shown in XMLTV and program guide. No upload = stock logo is used.</p>
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
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">FFmpeg profile</h2>
            <p className="text-white">{channel.ffmpeg_profile_name ?? channel.ffmpeg_profile_id ?? 'default'}</p>
          </section>
        </div>
        </>}
      </div>
    </div>
  )
}
