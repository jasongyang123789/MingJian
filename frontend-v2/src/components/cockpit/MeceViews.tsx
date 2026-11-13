import type { DecompositionBranch, DecompositionTree, MeceValidationResult } from '../../api/engineTypes'

function BranchNode({ branch, depth }: { branch: DecompositionBranch; depth: number }) {
  return (
    <li>
      <div className="flex flex-wrap items-baseline gap-2 py-1">
        <span className="text-sm font-medium text-slate-200">{branch.name}</span>
        {branch.scope.map((tag) => (
          <span
            key={tag}
            className="rounded-full border border-slate-700/60 bg-slate-800/40 px-2 py-0.5 font-mono text-[11px] text-slate-300"
          >
            {tag}
          </span>
        ))}
        {branch.scope.length === 0 && <span className="text-xs text-slate-600">（无 scope 标签）</span>}
      </div>
      {branch.children.length > 0 && (
        <ul className="ml-4 space-y-1 border-l border-slate-800 pl-4">
          {branch.children.map((child, index) => (
            <BranchNode key={`${child.name}-${index}`} branch={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function MeceTreeView({ tree }: { tree: DecompositionTree }) {
  return (
    <div>
      {tree.topic && <p className="mb-2 text-sm text-slate-400">{tree.topic}</p>}
      <ul>
        <BranchNode branch={tree.root} depth={0} />
      </ul>
    </div>
  )
}

const ISSUE_KIND_LABELS: Record<string, string> = {
  overlap: '重叠',
  gap: '缺口',
  extra: '多余',
  duplicate_tag: '重复标签',
  empty_branch: '空分支',
  empty_tree: '空树',
  max_depth_exceeded: '超出深度上限',
}

export function MeceValidationView({ validation }: { validation: MeceValidationResult }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
            validation.is_mece
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/20 bg-red-500/10 text-red-400'
          }`}
        >
          {validation.is_mece ? 'MECE 通过' : 'MECE 未通过'}
        </span>
        <span className="text-xs text-slate-500">
          {validation.branch_count} 个分支 · {validation.scope_tag_count} 个 scope 标签 ·{' '}
          {validation.issues.length} 个问题
        </span>
      </div>

      {validation.issues.length > 0 && (
        <div className="space-y-2">
          {validation.issues.map((issue, index) => (
            <div
              key={index}
              className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2"
              role="alert"
            >
              <p className="text-sm text-red-300">
                {ISSUE_KIND_LABELS[issue.kind] ?? issue.kind} · 节点「{issue.node}」
              </p>
              <p className="mt-0.5 text-xs leading-5 text-slate-400">{issue.detail}</p>
              {issue.tags.length > 0 && (
                <p className="mt-1 font-mono text-[11px] text-slate-500">标签：{issue.tags.join(', ')}</p>
              )}
              {issue.branches.length > 0 && (
                <p className="mt-0.5 font-mono text-[11px] text-slate-500">
                  分支：{issue.branches.join(', ')}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {validation.checks.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-3 font-medium">节点</th>
              <th className="py-2 pr-3 font-medium">检查</th>
              <th className="py-2 pr-3 font-medium">结果</th>
              <th className="py-2 font-medium">说明</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {validation.checks.map((check, index) => (
              <tr key={index}>
                <td className="py-2 pr-3 text-slate-300">{check.node}</td>
                <td className="py-2 pr-3 font-mono text-xs text-slate-400">{check.check}</td>
                <td className="py-2 pr-3">
                  <span className={check.status === 'PASS' ? 'text-emerald-400' : 'text-red-400'}>
                    {check.status}
                  </span>
                </td>
                <td className="py-2 text-xs leading-5 text-slate-400">{check.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
