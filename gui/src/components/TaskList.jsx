import { useState, useRef, useEffect } from 'react'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

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

const MicIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 1a4 4 0 0 1 4 4v7a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm0 2a2 2 0 0 0-2 2v7a2 2 0 0 0 4 0V5a2 2 0 0 0-2-2zm7 8a1 1 0 0 1 1 1 8 8 0 0 1-7 7.938V22h2a1 1 0 0 1 0 2H9a1 1 0 0 1 0-2h2v-2.062A8 8 0 0 1 4 12a1 1 0 0 1 2 0 6 6 0 0 0 12 0 1 1 0 0 1 1-1z"/>
  </svg>
)

const WAKE_SETTING_KEY = 'llmos.wakeEnabled'

function formatVoiceError(err) {
  if (!err) return 'Voice input failed.'
  if (typeof err === 'string') return err
  if (typeof err === 'object' && 'message' in err && typeof err.message === 'string') {
    return err.message
  }
  return 'Voice input failed.'
}

function formatMicrophonePermissionError(err) {
  const name = typeof err === 'object' && err && 'name' in err ? err.name : ''
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return 'Microphone access is blocked. Allow ShellMind in System Settings > Privacy & Security > Microphone, then relaunch the bundled app.'
  }
  if (name === 'NotFoundError') {
    return 'No microphone was found for voice input.'
  }
  if (name === 'NotReadableError') {
    return 'Your microphone is busy or unavailable right now.'
  }
  return `Microphone access failed${name ? `: ${name}` : '.'}`
}

export default function TaskList({ tasks, selectedTaskId, onSelect, onSubmit, loading, error }) {
  const [intent, setIntent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [listening, setListening] = useState(false)
  const [browserVoiceSupported] = useState(() =>
    typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  )
  const [wakeStatus, setWakeStatus] = useState({
    supported: false,
    enabled: false,
    wakePhrase: 'Hey Shell',
    lastError: null,
  })
  const [wakeBusy, setWakeBusy] = useState(false)
  const recognitionRef = useRef(null)
  const startVoiceCaptureRef = useRef(async () => false)
  const tauriDesktop = typeof window !== 'undefined' && isTauri()
  const canUseVoiceInput = tauriDesktop || browserVoiceSupported
  const wakeAvailable = tauriDesktop && wakeStatus.supported

  // Clean up recognition on unmount
  useEffect(() => () => recognitionRef.current?.abort(), [])

  useEffect(() => {
    if (!tauriDesktop) return undefined

    let active = true
    let removeWakeListener = null
    let removeStatusListener = null

    async function bootstrapWakeControls() {
      try {
        const status = await invoke('voice_get_status')
        if (!active) return

        setWakeStatus(status)

        const shouldEnable =
          window.localStorage.getItem(WAKE_SETTING_KEY) === 'true'

        if (shouldEnable && status.supported && !status.enabled) {
          const nextStatus = await invoke('voice_set_enabled', { enabled: true })
          if (!active) return
          setWakeStatus(nextStatus)
        }
      } catch (err) {
        if (active) {
          setWakeStatus(current => ({
            ...current,
            lastError: formatVoiceError(err),
          }))
        }
      }

      try {
        removeWakeListener = await listen('voice://wake-detected', () => {
          window.setTimeout(() => {
            void startVoiceCaptureRef.current({ clearIntent: true, trigger: 'wake' })
          }, 250)
        })
        removeStatusListener = await listen('voice://status-changed', event => {
          if (active) {
            setWakeStatus(event.payload)
          }
        })
      } catch (err) {
        if (active) {
          setWakeStatus(current => ({
            ...current,
            lastError: formatVoiceError(err),
          }))
        }
      }
    }

    bootstrapWakeControls()

    return () => {
      active = false
      removeWakeListener?.()
      removeStatusListener?.()
    }
  }, [tauriDesktop])

  async function submitIntent(nextIntent) {
    setSubmitting(true)
    setSubmitError(null)
    try {
      await onSubmit(nextIntent)
      setIntent('')
    } catch (err) {
      setSubmitError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function ensureMicrophonePermission() {
    if (!navigator.mediaDevices?.getUserMedia) {
      return { ok: false, error: 'This webview does not expose microphone capture. Native dictation is required here.' }
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(track => track.stop())
      return { ok: true }
    } catch (err) {
      return { ok: false, error: formatMicrophonePermissionError(err) }
    }
  }

  async function startVoiceCapture({ clearIntent = false, trigger = 'manual' } = {}) {
    if (listening || submitting || !canUseVoiceInput) return false

    if (tauriDesktop) {
      if (clearIntent) setIntent('')
      setListening(true)
      setSubmitError(null)

      try {
        const transcript = await invoke('voice_transcribe_once')
        setListening(false)

        if (typeof transcript === 'string' && transcript.trim()) {
          setIntent(transcript.trim())
          setTimeout(() => {
            submitIntent(transcript.trim())
          }, 150)
        }

        return true
      } catch (err) {
        setListening(false)
        setSubmitError(formatVoiceError(err))
        return false
      }
    }

    const micPermission = await ensureMicrophonePermission()
    if (!micPermission.ok) {
      setSubmitError(micPermission.error)
      return false
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = true
    recognition.continuous = false

    if (clearIntent) setIntent('')

    let finalTranscript = ''

    recognition.onstart = () => {
      setListening(true)
      setSubmitError(null)
    }
    recognition.onresult = (e) => {
      let interim = ''
      let final = ''
      for (const result of e.results) {
        if (result.isFinal) final += result[0].transcript
        else interim += result[0].transcript
      }
      if (final) finalTranscript = final
      setIntent(finalTranscript || interim)
    }
    recognition.onend = () => {
      setListening(false)
      recognitionRef.current = null
      if (finalTranscript.trim()) {
        setIntent(finalTranscript.trim())
        // Small delay so the input visually updates before submitting
        setTimeout(() => {
          submitIntent(finalTranscript.trim())
        }, 150)
      }
    }
    recognition.onerror = (event) => {
      setListening(false)
      recognitionRef.current = null
      if (event.error !== 'aborted') {
        if (event.error === 'service-not-allowed' && trigger === 'wake') {
          setSubmitError('Wake phrase heard, but automatic dictation was blocked by the webview speech service. We need native dictation for true hands-free input here.')
        } else if (event.error === 'service-not-allowed' || event.error === 'not-allowed') {
          setSubmitError('Microphone permission looks okay, but speech recognition is still blocked in this webview. Native dictation in Tauri is the next fix.')
        } else {
          setSubmitError(`Voice input failed: ${event.error}`)
        }
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch (err) {
      setSubmitError(`Voice input failed to start: ${formatVoiceError(err)}`)
      recognitionRef.current = null
      return false
    }
    return true
  }

  startVoiceCaptureRef.current = startVoiceCapture

  function toggleVoice() {
    if (listening) {
      recognitionRef.current?.stop()
      return
    }

    void startVoiceCapture()
  }

  async function toggleWakeListening() {
    if (!wakeAvailable || wakeBusy) return

    const nextEnabled = !wakeStatus.enabled
    setWakeBusy(true)

    try {
      const nextStatus = await invoke('voice_set_enabled', { enabled: nextEnabled })
      setWakeStatus(nextStatus)
      window.localStorage.setItem(WAKE_SETTING_KEY, String(nextStatus.enabled))
    } catch (err) {
      setWakeStatus(current => ({
        ...current,
        enabled: false,
        lastError: formatVoiceError(err),
      }))
      window.localStorage.setItem(WAKE_SETTING_KEY, 'false')
    } finally {
      setWakeBusy(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmed = intent.trim()
    if (!trimmed) return
    // Stop listening if mic is active
    recognitionRef.current?.stop()
    await submitIntent(trimmed)
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

      <div className="voice-control-bar">
        <div className="voice-control-copy">
          <span className={`voice-indicator${wakeStatus.enabled ? ' enabled' : ''}`} />
          <div>
            <strong>Hey Shell</strong>
            <p>
          {wakeAvailable
                ? `Say "${wakeStatus.wakePhrase}" to open ShellMind and start dictation.`
                : tauriDesktop && wakeStatus.supported
                  ? 'Wake detection is ready. Native dictation is used in the desktop app.'
                  : 'Wake listening is available in the macOS desktop app.'}
            </p>
          </div>
        </div>
        <button
          type="button"
          className={`voice-toggle${wakeStatus.enabled ? ' enabled' : ''}`}
          onClick={toggleWakeListening}
          disabled={wakeBusy || !wakeAvailable}
          title={
            wakeAvailable
              ? wakeStatus.enabled
                ? 'Disable wake listening'
                : 'Enable wake listening'
              : 'Wake listening is unavailable in this runtime'
          }
        >
          {wakeBusy ? 'Updating…' : wakeStatus.enabled ? 'On' : 'Off'}
        </button>
      </div>

      {wakeStatus.lastError && (
        <div className="voice-status-error">
          {wakeStatus.lastError}
        </div>
      )}

      {/* Submit form */}
      <form className="submit-form" onSubmit={handleSubmit}>
        <div className={`input-wrapper${listening ? ' input-listening' : ''}${submitting ? ' input-submitting' : ''}`}>
          <input
            type="text"
            placeholder={listening ? 'Listening…' : 'Describe a task in plain English…'}
            value={intent}
            onChange={e => setIntent(e.target.value)}
            disabled={submitting}
          />
          {canUseVoiceInput && (
            <button
              type="button"
              className={`mic-btn${listening ? ' listening' : ''}`}
              onClick={toggleVoice}
              disabled={submitting || (tauriDesktop && listening)}
              title={listening ? 'Listening…' : 'Speak a task'}
            >
              <MicIcon />
            </button>
          )}
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !intent.trim()}>
          {submitting ? <span className="btn-submitting-dots"><span/><span/><span/></span> : 'Run'}
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
