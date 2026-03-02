import { useState } from 'react'

export default function ApprovalModal({ task, onApprove, onReject }) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  // Find the step that is currently waiting for approval:
  // it has requires_approval=true and hasn't succeeded yet
  const pendingStep = task.steps?.find(
    s => s.requires_approval && s.state !== 'SUCCESS'
  )

  async function handleApprove() {
    setBusy(true)
    try {
      await onApprove(comment)
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    setBusy(true)
    try {
      await onReject(comment)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="modal-title">
          <span>⚠</span>
          Approval Required
        </div>
        <div className="modal-subtitle">
          A step needs your review before it can execute.
        </div>

        {pendingStep ? (
          <>
            <div className="modal-step-desc">
              <strong>Step #{pendingStep.order}:</strong> {pendingStep.description}
            </div>
            <div className="modal-command">{pendingStep.command}</div>
          </>
        ) : (
          <div className="modal-step-desc" style={{ color: 'var(--muted)' }}>
            Awaiting step details…
          </div>
        )}

        <textarea
          className="modal-comment"
          placeholder="Optional comment (reason for approval or rejection)…"
          value={comment}
          onChange={e => setComment(e.target.value)}
          disabled={busy}
        />

        <div className="modal-actions">
          <button className="btn btn-danger" onClick={handleReject} disabled={busy}>
            {busy ? '…' : 'Reject ✗'}
          </button>
          <button className="btn btn-success" onClick={handleApprove} disabled={busy}>
            {busy ? '…' : 'Approve ✓'}
          </button>
        </div>
      </div>
    </div>
  )
}
