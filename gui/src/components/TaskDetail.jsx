import ApprovalModal from './ApprovalModal'

// ── Helpers ──────────────────────────────────────────────────────────

const STATE_CLASS = {
  PENDING: 'pending',
  PLANNING: 'planning',
  RUNNING: 'running',
  AWAITING_APPROVAL: 'awaiting',
  SUCCESS: 'success',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
}

const STATE_LABEL = {
  PENDING: 'Pending',
  PLANNING: 'Planning',
  RUNNING: 'Running',
  AWAITING_APPROVAL: 'Needs Approval',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

// Step state → icon + CSS class
const STEP_ICON = {
  PENDING: { char: '○', cls: 'pending' },
  RUNNING: { char: '●', cls: 'running' },
  SUCCESS: { char: '✓', cls: 'success' },
  FAILED:  { char: '✗', cls: 'failed' },
  SKIPPED: { char: '—', cls: 'skipped' },
}

// Risk level → display
const RISK_DISPLAY = {
  SAFE:    { label: null,      cls: 'risk-safe' },
  RISKY:   { label: '! Risky', cls: 'risk-risky' },
  BLOCKED: { label: '✗ Blocked', cls: 'risk-blocked' },
}

function StateBadge({ state }) {
  const cls = STATE_CLASS[state] ?? 'pending'
  return <span className={`badge badge-${cls}`}>{STATE_LABEL[state] ?? state}</span>
}

function formatDuration(start, end) {
  if (!start || !end) return null
  const ms = new Date(end) - new Date(start)
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ── StepCard ─────────────────────────────────────────────────────────

function StepCard({ step }) {
  const icon = STEP_ICON[step.state] ?? STEP_ICON.PENDING
  const risk = RISK_DISPLAY[step.risk_level] ?? RISK_DISPLAY.SAFE
  const duration = formatDuration(step.started_at, step.finished_at)

  const hasOutput = step.stdout || step.stderr

  return (
    <div className="step-card">
      <div className="step-header">
        {/* State icon */}
        <span className={`step-icon step-icon-${icon.cls}`}>{icon.char}</span>

        {/* Order */}
        <span className="step-order">#{step.order}</span>

        {/* Description */}
        <span className="step-description">{step.description}</span>

        {/* Risk badge */}
        {risk.label && <span className={risk.cls}>{risk.label}</span>}

        {/* Timing */}
        {duration && <span className="step-timing">{duration}</span>}

        {/* Exit code badge */}
        {step.exit_code != null && step.exit_code !== 0 && (
          <span style={{ fontSize: 11, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>
            exit {step.exit_code}
          </span>
        )}
      </div>

      {/* Command */}
      <div className="step-command">{step.command}</div>

      {/* Output (stdout / stderr) */}
      {hasOutput && (
        <details className="step-output">
          <summary>
            Output
            {step.exit_code != null && ` · exit ${step.exit_code}`}
          </summary>
          {step.stdout && <pre className="stdout-pre">{step.stdout}</pre>}
          {step.stderr && <pre className="stderr-pre">{step.stderr}</pre>}
        </details>
      )}
    </div>
  )
}

// ── TaskDetail ────────────────────────────────────────────────────────

export default function TaskDetail({ task, onApprove, onReject }) {
  const shortId = task.id.slice(0, 8)
  const createdAt = new Date(task.created_at).toLocaleString()

  return (
    <div className="task-detail-panel">
      {/* Header */}
      <div className="task-detail-header">
        <div style={{ flex: 1 }}>
          <div className="intent">{task.intent}</div>
          <div className="meta">{shortId} · {createdAt}</div>
        </div>
        <StateBadge state={task.state} />
      </div>

      {/* Body */}
      <div className="task-detail-body">
        {/* Error banner */}
        {task.error_msg && (
          <div className="error-banner">Error: {task.error_msg}</div>
        )}

        {/* Steps */}
        {task.steps && task.steps.length > 0 ? (
          <div className="steps-list">
            {task.steps.map(step => (
              <StepCard key={step.id} step={step} />
            ))}
          </div>
        ) : (
          <div style={{ color: 'var(--muted)', fontSize: 13, marginTop: 8 }}>
            No steps yet — task is being planned.
          </div>
        )}
      </div>

      {/* Approval modal (overlays when task needs approval) */}
      {task.state === 'AWAITING_APPROVAL' && (
        <ApprovalModal
          task={task}
          onApprove={onApprove}
          onReject={onReject}
        />
      )}
    </div>
  )
}
