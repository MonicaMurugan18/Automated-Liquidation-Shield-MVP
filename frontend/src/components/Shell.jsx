import { useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import {
  GaugeCircle,
  History,
  LayoutGrid,
  Menu,
  Scale,
  Settings as SettingsIcon,
  ShieldHalf,
  Sparkles,
  TrendingDown,
  X,
} from 'lucide-react'
import StatusBar from './StatusBar'
import DemoControls from './DemoControls'
import { ErrorBanner } from './ui'
import { useShield } from '../state/ShieldContext'

const NAV = [
  { to: '/portal', label: 'Dashboard', Icon: GaugeCircle, end: true },
  { to: '/portal/position', label: 'Position', Icon: LayoutGrid },
  { to: '/portal/scenarios', label: 'Scenarios', Icon: TrendingDown },
  { to: '/portal/strategies', label: 'Strategies', Icon: Sparkles },
  { to: '/portal/comparison', label: 'Comparison', Icon: Scale },
  { to: '/portal/history', label: 'History', Icon: History },
  { to: '/portal/settings', label: 'Settings', Icon: SettingsIcon },
]

function NavItems({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV.map(({ to, label, Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-2.5 rounded-md px-3 py-2 font-display text-sm transition-colors ${
              isActive
                ? 'bg-panel-raised text-ink'
                : 'text-muted hover:bg-panel-raised/60 hover:text-ink'
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon size={16} aria-hidden="true" className={isActive ? 'text-safe' : ''} />
              {label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

export default function Shell() {
  const { error, clearError } = useShield()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-screen bg-base">
      <StatusBar />

      <div className="mx-auto flex max-w-[1400px] gap-6 px-4 py-5 sm:px-6">
        {/* Desktop rail */}
        <aside className="hidden w-52 shrink-0 lg:block">
          <div className="sticky top-20 flex flex-col gap-5">
            <Link
              to="/"
              className="flex items-center gap-2 rounded-md px-1 py-1 transition-colors hover:bg-panel-raised"
            >
              <ShieldHalf size={20} className="text-safe" aria-hidden="true" />
              <div>
                <p className="font-display text-sm leading-tight font-semibold text-ink">
                  Liquidation Shield
                </p>
                <p className="text-[11px] leading-tight text-muted">Back to control center</p>
              </div>
            </Link>
            <NavItems />
            <DemoControls />
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          {/* Mobile header */}
          <div className="mb-4 flex items-center justify-between lg:hidden">
            <Link to="/" className="flex items-center gap-2">
              <ShieldHalf size={18} className="text-safe" aria-hidden="true" />
              <span className="font-display text-sm font-semibold">Liquidation Shield</span>
            </Link>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              className="rounded-md border border-hairline p-2 text-muted hover:text-ink"
            >
              {menuOpen ? <X size={16} /> : <Menu size={16} />}
            </button>
          </div>

          {menuOpen && (
            <div className="mb-4 flex flex-col gap-4 rounded-lg border border-hairline bg-panel p-3 lg:hidden">
              <NavItems onNavigate={() => setMenuOpen(false)} />
              <DemoControls />
            </div>
          )}

          {error && (
            <div className="mb-4">
              <ErrorBanner message={error} onDismiss={clearError} />
            </div>
          )}

          <Outlet />

          <footer className="mt-8 border-t border-hairline pt-4 text-xs text-muted">
            Simulated environment. No transaction is signed or broadcast; market,
            gas and DEX data are modelled in the Python engines.
          </footer>
        </main>
      </div>
    </div>
  )
}
