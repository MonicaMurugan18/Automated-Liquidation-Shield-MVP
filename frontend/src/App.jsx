import { Route, Routes } from 'react-router-dom'
import { ShieldAlert, ShieldHalf } from 'lucide-react'
import Shell from './components/Shell'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import PositionOverview from './pages/PositionOverview'
import ScenarioPrediction from './pages/ScenarioPrediction'
import ProtectionSuggestions from './pages/ProtectionSuggestions'
import StrategyComparison from './pages/StrategyComparison'
import RescueHistory from './pages/RescueHistory'
import Settings from './pages/Settings'
import { useShield } from './state/ShieldContext'
import { Button } from './components/ui'

function Splash({ icon: Icon, title, children, tone = 'muted' }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-base px-6">
      <div className="flex max-w-md flex-col items-center gap-3 text-center">
        <Icon
          size={28}
          className={tone === 'danger' ? 'text-danger' : 'text-safe'}
          aria-hidden="true"
        />
        <h1 className="font-display text-lg text-ink">{title}</h1>
        <p className="text-sm text-muted">{children}</p>
      </div>
    </div>
  )
}

/**
 * The protection portal: everything that needs live engine data.
 *
 * The landing page deliberately sits outside this gate. A visitor should be
 * able to read what the system does even when the backend is down; the portal
 * cannot open without it, so it waits here.
 */
function Portal() {
  const { booted, bootError, retryBoot } = useShield()

  if (bootError) {
    return (
      <Splash icon={ShieldAlert} title="Protection service unreachable" tone="danger">
        {bootError} Start the backend with{' '}
        <code className="tabular text-ink">uvicorn app.main:app --port 8000</code> from the
        backend directory, then retry.
        <span className="mt-4 block">
          <Button variant="primary" onClick={retryBoot}>
            Retry connection
          </Button>
        </span>
      </Splash>
    )
  }

  if (!booted) {
    return (
      <Splash icon={ShieldHalf} title="Arming the shield">
        Loading position, scenarios and strategies from the protection engine…
      </Splash>
    )
  }

  return <Shell />
}

export default function App() {
  return (
    <Routes>
      {/* Landing dashboard -- the entrance to the control room. */}
      <Route path="/" element={<Landing />} />

      {/* The existing application, unchanged, now reached at /portal. */}
      <Route path="/portal" element={<Portal />}>
        <Route index element={<Dashboard />} />
        <Route path="position" element={<PositionOverview />} />
        <Route path="scenarios" element={<ScenarioPrediction />} />
        <Route path="strategies" element={<ProtectionSuggestions />} />
        <Route path="comparison" element={<StrategyComparison />} />
        <Route path="history" element={<RescueHistory />} />
        <Route path="settings" element={<Settings />} />
        <Route
          path="*"
          element={
            <div className="rounded-lg border border-hairline bg-panel p-6 text-sm text-muted">
              Page not found.
            </div>
          }
        />
      </Route>

      <Route
        path="*"
        element={
          <Splash icon={ShieldAlert} title="Page not found" tone="danger">
            That route does not exist. Head back to the landing dashboard or open the protection
            portal.
          </Splash>
        }
      />
    </Routes>
  )
}
