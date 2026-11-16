import { Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import { ErrorBoundary } from './components/ui/ErrorBoundary'
import Dashboard from './pages/Dashboard'
import AiAssistant from './pages/AiAssistant'
import Workbench from './pages/Workbench'
import Agents from './pages/Agents'
import Debate from './pages/Debate'
import Simulation from './pages/Simulation'
import Evidence from './pages/Evidence'
import Sources from './pages/Sources'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Monitoring from './pages/Monitoring'
import Cockpit from './pages/Cockpit'
import Automotive from './pages/Automotive'
import Charts from './pages/Charts'
import Deliberation from './pages/Deliberation'
import Directions from './pages/Directions'
import LivingLoop from './pages/LivingLoop'
import MeceAuthoring from './pages/MeceAuthoring'
import TemplateProvenance from './pages/TemplateProvenance'
import VariableTemplates from './pages/VariableTemplates'
import { AuthGate } from './auth/AuthGate'

export default function App() {
  return (
    <ErrorBoundary>
      <AuthGate>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/ai-assistant" element={<AiAssistant />} />
            <Route path="/workbench" element={<Workbench />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/debate" element={<Debate />} />
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/evidence" element={<Evidence />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/predictions" element={<Navigate to="/reports" replace />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/cockpit" element={<Cockpit />} />
            <Route path="/cockpit/deliberations" element={<Deliberation />} />
            <Route path="/cockpit/mece" element={<MeceAuthoring />} />
            <Route path="/cockpit/variable-templates" element={<VariableTemplates />} />
            <Route path="/cockpit/charts" element={<Charts />} />
            <Route path="/cockpit/loops" element={<LivingLoop />} />
            <Route path="/cockpit/directions" element={<Directions />} />
            <Route path="/cockpit/templates" element={<TemplateProvenance />} />
            <Route path="/cockpit/automotive" element={<Automotive />} />
          </Route>
        </Routes>
      </AuthGate>
    </ErrorBoundary>
  )
}
