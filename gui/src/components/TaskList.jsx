import { useState } from 'react'

// Map a TaskState → CSS class suffix
const STATE_CLASS = {
  PENDING: 'pending',
  PLANNING: 'planning',
  RUNNING: 'running',
  AWAITING_APPROVAL: 'awaiting',
  SUCCESS: 'success',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
}

// Human-readable label for each state
const STATE_LABEL = {
  PENDING: 'Pending',
  PLANNING: 'Planning',
  RUNNING: 'Running',
  AWAITING_APPROVAL: 'Needs Approval',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

function StateBadge({ state }) {
  const cls = STATE_CLASS[state] ?? 'pending'
  return <span className={`badge badge-${cls}`}>{STATE_LABEL[state] ?? state}</span>
}

export default function TaskList({ tasks, selectedTaskId, onSelect, onSubmit, loading, error }) {
  const [intent, setIntent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmed = intent.trim()
    if (!trimmed) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await onSubmit(trimmed)
      setIntent('')
    } catch (err) {
      setSubmitError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="task-list-panel">
      {/* Panel header */}
      <div className="task-list-header">
        <h2>Tasks</h2>
        <span style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: 'var(--green)', boxShadow: '0 0 4px var(--green)' }} />
          Live
        </span>
      </div>

      {/* Submit form */}
      <form className="submit-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Describe a task in plain English…"
          value={intent}
          onChange={e => setIntent(e.target.value)}
          disabled={submitting}
        />
        <button className="btn btn-primary" type="submit" disabled={submitting || !intent.trim()}>
          {submitting ? '…' : 'Run'}
        </button>
      </form>

      {/* Errors */}
      {submitError && (
        <div style={{ padding: '6px 14px', color: 'var(--red)', fontSize: 12 }}>
          {submitError}
        </div>
      )}
      {error && (
        <div style={{ padding: '6px 14px', color: 'var(--red)', fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Task rows */}
      <div className="task-table">
        {tasks.length === 0 && !loading && (
          <div className="empty-state">
            No tasks yet.<br />Type a task above and press Run.
          </div>
        )}

        {tasks.map(task => {
          const stepCount = task.steps?.length ?? 0
          const truncated = task.intent.length > 60
            ? task.intent.slice(0, 60) + '…'
            : task.intent
          const isSelected = task.id === selectedTaskId

          return (
            <div
              key={task.id}
              className={`task-row${isSelected ? ' selected' : ''}`}
              onClick={() => onSelect(task.id)}
            >
              <StateBadge state={task.state} />
              <span className="intent" title={task.intent}>{truncated}</span>
              <span className="step-count">
                {stepCount > 0 ? `${stepCount} step${stepCount !== 1 ? 's' : ''}` : ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
