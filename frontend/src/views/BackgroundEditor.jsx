import { useState, useEffect, useRef } from 'react'
import { getBackgrounds, uploadBackground, updateBackground, deleteBackground } from '../api'

const STOCK_PREVIEW = '/static/stock-background.png'

export default function BackgroundEditor() {
  const [backgrounds, setBackgrounds] = useState([])
  const [selected, setSelected] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [saved, setSaved] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const fileInputRef = useRef(null)
  const canvasRef = useRef(null)
  const [dragState, setDragState] = useState(null)

  useEffect(() => {
    getBackgrounds().then(setBackgrounds).catch(() => setBackgrounds([]))
  }, [])

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const bg = await uploadBackground(file, file.name.replace(/\.[^.]+$/, ''))
      setBackgrounds((prev) => [...prev, bg])
      setSelected(bg.id)
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const selectedBg = backgrounds.find((b) => b.id === selected)

  const overlayKeys = ['channel_name', 'song_title', 'artist_name', 'artist_image', 'artist_bio']

  const toHexForPicker = (c, defaultHex = '#ffffff') => {
    if (!c || typeof c !== 'string') return defaultHex
    if (c.startsWith('#')) return c.length >= 7 ? c.slice(0, 7) : defaultHex
    const names = { white: '#ffffff', black: '#000000', red: '#ff0000', yellow: '#ffff00', blue: '#0000ff' }
    return names[c.toLowerCase()] || defaultHex
  }

  const ensurePlacements = (bg) => {
    if (!bg || (bg.overlay_placements && bg.overlay_placements.length)) return bg
    const seeded = {
      ...bg,
      overlay_placements: [
        { key: 'channel_name', x: 5, y: 5, width: 35, height: 6, font_size: 28, anchor: 'nw', font_color: 'white', shadow_color: 'black', font_family: '' },
        { key: 'song_title', x: 10, y: 72, width: 40, height: 8, font_size: 34, anchor: 'nw', font_color: 'white', shadow_color: 'black', font_family: '' },
        { key: 'artist_name', x: 10, y: 78, width: 30, height: 7, font_size: 28, anchor: 'nw', font_color: 'white', shadow_color: 'black', font_family: '' },
        { key: 'artist_image', x: 5, y: 19, width: 18, height: 30, font_size: 20, anchor: 'nw', font_color: 'white', shadow_color: 'black', font_family: '' },
        { key: 'artist_bio', x: 39, y: 39, width: 45, height: 12, font_size: 20, anchor: 'nw', font_color: 'white', shadow_color: 'black', font_family: '' },
      ],
    }
    setBackgrounds((prev) => prev.map((b) => (b.id === bg.id ? seeded : b)))
    return seeded
  }

  const currentBg = selectedBg && !selectedBg.is_stock ? ensurePlacements(selectedBg) : selectedBg
  const isStockLike = selected === 'stock' || selected === 'stock-dark'

  const handleMouseDown = (e, placement) => {
    if (!currentBg || currentBg.is_stock || isStockLike) return
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const px = ((placement.x ?? 0) / 100) * rect.width
    const py = ((placement.y ?? 0) / 100) * rect.height
    setDragState({
      key: placement.key,
      startX: e.clientX,
      startY: e.clientY,
      originPxX: px,
      originPxY: py,
      rectWidth: rect.width,
      rectHeight: rect.height,
    })
  }

  const handleMouseMove = (e) => {
    if (!dragState || !currentBg || currentBg.is_stock || isStockLike) return
    const dx = e.clientX - dragState.startX
    const dy = e.clientY - dragState.startY
    const newPxX = dragState.originPxX + dx
    const newPxY = dragState.originPxY + dy
    const nx = Math.min(100, Math.max(0, (newPxX / dragState.rectWidth) * 100))
    const ny = Math.min(100, Math.max(0, (newPxY / dragState.rectHeight) * 100))
    setBackgrounds((prev) =>
      prev.map((b) =>
        b.id === currentBg.id
          ? {
              ...b,
              overlay_placements: (b.overlay_placements || []).map((p) =>
                p.key === dragState.key ? { ...p, x: nx, y: ny } : p,
              ),
            }
          : b,
      ),
    )
  }

  const handleMouseUp = () => {
    setDragState(null)
  }

  const refetchBackgrounds = () => {
    getBackgrounds().then(setBackgrounds).catch(() => setBackgrounds([]))
  }

  const updatePlacement = (key, field, value) => {
    if (!currentBg || currentBg.is_stock || isStockLike) return
    setBackgrounds((prev) =>
      prev.map((b) =>
        b.id === currentBg.id
          ? {
              ...b,
              overlay_placements: (b.overlay_placements || []).map((p) =>
                p.key === key ? { ...p, [field]: value } : p,
              ),
            }
          : b,
      ),
    )
  }

  const handleSavePlacements = async () => {
    if (!currentBg || currentBg.is_stock || isStockLike) return
    const placements = (currentBg.overlay_placements || []).map((p) => ({
      key: p.key,
      x: Math.round(Number(p.x)) || 0,
      y: Math.round(Number(p.y)) || 0,
      width: Math.round(Number(p.width)) || 0,
      height: Math.round(Number(p.height)) || 0,
      font_size: Math.round(Number(p.font_size)) || 24,
      anchor: p.anchor || 'nw',
      font_color: p.font_color || 'white',
      shadow_color: p.shadow_color || 'black',
      font_family: p.font_family || '',
      hidden: Boolean(p.hidden),
    }))
    try {
      await updateBackground(currentBg.id, { overlay_placements: placements })
      refetchBackgrounds()
      setSaved(true)
      setTimeout(() => setSaved(false), 6000)
    } catch (e) {
      console.error(e)
    }
  }

  const handleRemoveBackground = async () => {
    if (!currentBg || currentBg.is_stock || isStockLike || !window.confirm(`Remove background "${currentBg.name || currentBg.id}"?`)) return
    setDeleting(true)
    try {
      await deleteBackground(currentBg.id)
      setSelected('stock')
      refetchBackgrounds()
    } catch (e) {
      console.error(e)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="p-6 max-w-7xl">
      <h1 className="text-2xl font-semibold text-white mb-2">background editor</h1>
      <p className="text-slate-400 text-sm mb-6">
        Import or edit a custom background. Adjust overlay placement (song title, artist name, artist image, artist bio) and save. (Select a background for each channel in channelz).
      </p>

      <div className="flex gap-6">
        <div className="w-72 shrink-0 space-y-4">
          <div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="w-full px-4 py-2 rounded-lg border border-surface-500 text-slate-300 font-medium hover:bg-surface-600 disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : 'Import image'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFile}
            />
          </div>
          <div className="border border-surface-500 rounded-lg overflow-hidden bg-surface-700/30">
            <div className="p-2 border-b border-surface-500 text-xs text-slate-400 uppercase tracking-wider">
              Saved backgrounds
            </div>
            <ul className="max-h-80 overflow-y-auto">
              {backgrounds.map((bg) => (
                <li key={bg.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(bg.id)}
                    className={`w-full text-left px-4 py-2.5 border-b border-surface-500/50 ${
                      selected === bg.id ? 'bg-accent-500/20 text-accent-400' : 'text-slate-300 hover:bg-surface-600'
                    }`}
                  >
                    {bg.name || bg.id}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <div className="rounded-xl border border-surface-500 bg-surface-700/50 overflow-hidden">
            <div
              ref={canvasRef}
              className="aspect-video min-h-[420px] bg-surface-600 flex items-center justify-center relative"
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
            >
              {/* Light grid overlay for placement design */}
              <div
                className="absolute inset-0 pointer-events-none"
                style={{
                  backgroundImage: `
                    linear-gradient(to right, rgba(255,255,255,0.4) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(255,255,255,0.4) 1px, transparent 1px)
                  `,
                  backgroundSize: '8% 8%',
                }}
              />
              {selected === 'stock' || !currentBg ? (
                <img
                  src={STOCK_PREVIEW}
                  alt="Stock background"
                  className="max-h-full max-w-full object-contain"
                />
              ) : selected === 'stock-dark' ? (
                <img
                  src="/api/backgrounds/stock-dark/image"
                  alt="Stock (Dark Theme)"
                  className="max-h-full max-w-full object-contain"
                />
              ) : currentBg?.image_path && !currentBg.is_stock ? (
                <>
                  <img
                    src={`/api/backgrounds/${currentBg.id}/image`}
                    alt={currentBg.name}
                    className="max-h-full max-w-full object-contain"
                  />
                  {/* Overlay boxes (percent-based positions) - only for custom backgrounds */}
                  {(currentBg.overlay_placements || [])
                    .filter((p) => overlayKeys.includes(p.key))
                    .map((p) => {
                      const isText = ['song_title', 'artist_name', 'artist_bio'].includes(p.key)
                      const fc = (p.font_color && p.font_color.startsWith('#')) ? p.font_color : (p.font_color || 'white')
                      const sc = (p.shadow_color && p.shadow_color.startsWith('#')) ? p.shadow_color : (p.shadow_color || 'black')
                      return (
                        <div
                          key={p.key}
                          onMouseDown={(e) => handleMouseDown(e, p)}
                          className={`absolute cursor-move border px-2 py-1 rounded ${p.hidden ? 'border-amber-500/80 bg-amber-900/40 opacity-70' : 'border-accent-500/80 bg-black/35'}`}
                          style={{
                            left: `${p.x ?? 0}%`,
                            top: `${p.y ?? 0}%`,
                            transform: 'translate(-0%, -0%)',
                            ...(p.key === 'artist_image' ? {
                              width: `${Math.max(5, Math.min(50, p.width || 18))}%`,
                              height: `${Math.max(5, Math.min(50, p.height || 30))}%`,
                              minWidth: '40px',
                              minHeight: '32px',
                              color: '#fff',
                              fontSize: '12px',
                            } : isText ? {
                              fontSize: `${Math.max(10, (p.font_size || 14))}px`,
                              color: fc,
                              textShadow: `1px 1px 0 ${sc}, 0 0 2px ${sc}`,
                            } : { color: '#fff', fontSize: '12px' }),
                          }}
                        >
                          {p.key === 'channel_name' && 'Channel name'}
                          {p.key === 'song_title' && 'Song title'}
                          {p.key === 'artist_name' && 'Artist name'}
                          {p.key === 'artist_image' && 'Artist image'}
                          {p.key === 'artist_bio' && 'Artist bio'}
                          {p.hidden && <span className="text-amber-400 text-xs ml-1">(hidden)</span>}
                        </div>
                      )
                    })}
                </>
              ) : (
                <span className="text-slate-500">Select or import a background</span>
              )}
            </div>
            <div className="p-4 border-t border-surface-500 space-y-3">
              {isStockLike ? (
                <p className="text-sm text-slate-400">
                  Stock backgrounds use fixed overlay positions. Import a custom background to adjust overlay placement.
                </p>
              ) : currentBg && !currentBg.is_stock ? (
                <>
                  <p className="text-sm text-slate-400">
                    Drag the overlay boxes to place them. Use the settings below for text size and colors, then Save placement.
                  </p>
                  {/* Per-overlay text settings (song, artist, bio) */}
                  <div className="space-y-3">
                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Text overlay settings</p>
                    {(currentBg.overlay_placements || [])
                      .filter((p) => ['channel_name', 'song_title', 'artist_name', 'artist_bio'].includes(p.key))
                      .map((p) => (
                        <div key={p.key} className="flex flex-wrap items-center gap-3 p-2 rounded bg-surface-600/50 border border-surface-500/50">
                          <span className="text-slate-300 text-sm w-28 shrink-0">
                            {p.key === 'channel_name' && 'Channel name'}
                            {p.key === 'song_title' && 'Song title'}
                            {p.key === 'artist_name' && 'Artist name'}
                            {p.key === 'artist_bio' && 'Artist bio'}
                          </span>
                          <label className="flex items-center gap-1.5 text-sm text-slate-400 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={Boolean(p.hidden)}
                              onChange={() => updatePlacement(p.key, 'hidden', !p.hidden)}
                              className="rounded border-surface-500 bg-surface-600 text-accent-500 focus:ring-accent-500"
                            />
                            <span>Hide in live feed</span>
                          </label>
                          <label className="flex items-center gap-1.5 text-sm text-slate-400">
                            Size
                            <input
                              type="number"
                              min="8"
                              max="72"
                              value={p.font_size || 24}
                              onChange={(e) => updatePlacement(p.key, 'font_size', parseInt(e.target.value, 10) || 24)}
                              className="w-14 px-2 py-1 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                            />
                          </label>
                          <label className="flex items-center gap-1.5 text-sm text-slate-400">
                            Text color
                            <input
                              type="color"
                              value={toHexForPicker(p.font_color)}
                              onChange={(e) => updatePlacement(p.key, 'font_color', e.target.value)}
                              className="w-8 h-8 rounded border border-surface-500 cursor-pointer"
                            />
                            <input
                              type="text"
                              placeholder="white or #hex"
                              value={p.font_color ?? 'white'}
                              onChange={(e) => updatePlacement(p.key, 'font_color', e.target.value)}
                              className="w-24 px-2 py-1 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                            />
                          </label>
                          <label className="flex items-center gap-1.5 text-sm text-slate-400">
                            Shadow
                            <input
                              type="color"
                              value={toHexForPicker(p.shadow_color, '#000000')}
                              onChange={(e) => updatePlacement(p.key, 'shadow_color', e.target.value)}
                              className="w-8 h-8 rounded border border-surface-500 cursor-pointer"
                            />
                            <input
                              type="text"
                              placeholder="black or #hex"
                              value={p.shadow_color ?? 'black'}
                              onChange={(e) => updatePlacement(p.key, 'shadow_color', e.target.value)}
                              className="w-24 px-2 py-1 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                            />
                          </label>
                        </div>
                      ))}
                  </div>
                  {/* Artist image size (for imported backgrounds only) */}
                  {(currentBg.overlay_placements || []).filter((p) => p.key === 'artist_image').map((p) => (
                    <div key={p.key} className="space-y-2 p-2 rounded bg-surface-600/50 border border-surface-500/50">
                      <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Artist image size</p>
                      <p className="text-sm text-slate-400">Scale the artist photo overlay. Values are percent of canvas width/height (default stream size 1280×720; configurable via MUZIC_OUTPUT_WIDTH / MUZIC_OUTPUT_HEIGHT).</p>
                      <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={Boolean(p.hidden)}
                          onChange={() => updatePlacement('artist_image', 'hidden', !p.hidden)}
                          className="rounded border-surface-500 bg-surface-600 text-accent-500 focus:ring-accent-500"
                        />
                        <span>Hide in live feed</span>
                      </label>
                      <div className="flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-2 text-sm text-slate-400">
                          Width (%)
                          <input
                            type="number"
                            min="5"
                            max="50"
                            value={Math.round(Number(p.width) || 18)}
                            onChange={(e) => updatePlacement('artist_image', 'width', Math.max(5, Math.min(50, parseInt(e.target.value, 10) || 18)))}
                            className="w-16 px-2 py-1 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                          />
                        </label>
                        <label className="flex items-center gap-2 text-sm text-slate-400">
                          Height (%)
                          <input
                            type="number"
                            min="5"
                            max="50"
                            value={Math.round(Number(p.height) || 30)}
                            onChange={(e) => updatePlacement('artist_image', 'height', Math.max(5, Math.min(50, parseInt(e.target.value, 10) || 30)))}
                            className="w-16 px-2 py-1 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                  <div className="flex items-center gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        placeholder="Background name"
                        value={currentBg.name}
                        onChange={(e) => {
                          const name = e.target.value
                          setBackgrounds((prev) => prev.map((b) => (b.id === currentBg.id ? { ...b, name } : b)))
                        }}
                        onBlur={async () => {
                          if (!currentBg.id) return
                          try {
                            await updateBackground(currentBg.id, { name: currentBg.name })
                            refetchBackgrounds()
                          } catch (e) {
                            console.error(e)
                          }
                        }}
                        className="flex-1 min-w-0 px-3 py-2 rounded bg-surface-600 border border-surface-500 text-white text-sm"
                      />
                      <button
                        type="button"
                        onClick={handleSavePlacements}
                        className="px-4 py-2 rounded-lg border border-surface-500 text-slate-200 text-sm font-medium hover:bg-surface-600"
                      >
                        {saved ? 'Saved' : 'Save placement'}
                      </button>
                      {saved && (
                        <span className="text-sm text-slate-400">
                          Restart the channel in Channelz to see overlay changes on the stream.
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={handleRemoveBackground}
                        disabled={deleting}
                        className="px-4 py-2 rounded-lg border border-red-500/60 text-red-400 text-sm font-medium hover:bg-red-500/10 disabled:opacity-50"
                      >
                        {deleting ? 'Removing…' : 'Remove background'}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-slate-400">
                  Select or import a background to edit overlay placements.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
