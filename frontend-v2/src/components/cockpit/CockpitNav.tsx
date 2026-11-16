import { NavLink } from 'react-router-dom'

const TABS = [
  { label: '推演驾驶舱', path: '/cockpit' },
  { label: 'Deliberation', path: '/cockpit/deliberations' },
  { label: 'MECE 编写', path: '/cockpit/mece' },
  { label: '变量模板', path: '/cockpit/variable-templates' },
  { label: '分布图表', path: '/cockpit/charts' },
  { label: '活战略循环', path: '/cockpit/loops' },
  { label: '决策方向', path: '/cockpit/directions' },
  { label: '模板出处', path: '/cockpit/templates' },
  { label: '汽车推演', path: '/cockpit/automotive' },
]

export function CockpitNav() {
  return (
    <nav className="flex flex-wrap gap-2" aria-label="驾驶舱">
      {TABS.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          end={tab.path === '/cockpit'}
          className={({ isActive }) =>
            `rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
              isActive
                ? 'border-blue-500/30 bg-blue-500/10 font-medium text-blue-300'
                : 'border-slate-700/50 bg-slate-800/30 text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
            }`
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
