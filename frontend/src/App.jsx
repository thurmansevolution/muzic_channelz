import { useState } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import Home from './views/Home'
import Channelz from './views/Channelz'
import ChannelDetail from './views/ChannelDetail'
import Administration from './views/Administration'
import BackgroundEditor from './views/BackgroundEditor'
import LiveLogs from './views/LiveLogs'

const SECTIONS = [
  { id: 'home', label: 'home', path: '/' },
  { id: 'channelz', label: 'channelz', path: '/channelz' },
  { id: 'administration', label: 'administration', path: '/administration' },
  { id: 'background-editor', label: 'background editor', path: '/background-editor' },
  { id: 'live-logs', label: 'live logs', path: '/live-logs' },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const currentSection = SECTIONS.find(s => {
    if (s.path === '/') return location.pathname === '/'
    return location.pathname.startsWith(s.path)
  })?.id ?? 'home'

  return (
    <div className="flex h-screen overflow-hidden bg-surface-800">
      <aside
        className={`${
          sidebarCollapsed ? 'w-14' : 'w-56'
        } flex flex-col border-r border-surface-500 bg-surface-700 transition-all duration-200 shrink-0`}
      >
        <div className="p-3 border-b border-surface-500 flex items-center justify-between">
          {!sidebarCollapsed && (
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Sections
            </span>
          )}
          <button
            type="button"
            onClick={() => setSidebarCollapsed(c => !c)}
            className="p-1.5 rounded text-slate-400 hover:bg-surface-600 hover:text-white"
            aria-label={sidebarCollapsed ? 'Expand' : 'Collapse'}
          >
            {sidebarCollapsed ? '→' : '←'}
          </button>
        </div>
        <nav className="flex-1 py-2 overflow-y-auto">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => navigate(s.path)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                currentSection === s.id
                  ? 'bg-accent-500/20 text-accent-400 border-l-2 border-accent-500'
                  : 'text-slate-300 hover:bg-surface-600 hover:text-white border-l-2 border-transparent'
              } ${sidebarCollapsed ? 'justify-center px-0' : ''}`}
            >
              {s.id === 'home' && <span className="text-lg">🏠</span>}
              {s.id === 'channelz' && <span className="text-lg">📺</span>}
              {s.id === 'administration' && <span className="text-lg">⚙</span>}
              {s.id === 'background-editor' && <span className="text-lg">🖼</span>}
              {s.id === 'live-logs' && <span className="text-lg">📋</span>}
              {!sidebarCollapsed && <span className="font-medium">{s.label}</span>}
            </button>
          ))}
        </nav>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-auto">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/channelz" element={<Channelz />} />
          <Route path="/channelz/:channelId" element={<ChannelDetail />} />
          <Route path="/administration" element={<Administration />} />
          <Route path="/background-editor" element={<BackgroundEditor />} />
          <Route path="/live-logs" element={<LiveLogs />} />
          <Route path="/live-logs/:channelId" element={<LiveLogs />} />
        </Routes>
      </main>
    </div>
  )
}
