const BASE = 'http://localhost:7777'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

export function fetchTasks() {
  return request('/tasks')
}

export function fetchTask(id) {
  return request(`/tasks/${id}`)
}

export function createTask(intent) {
  return request('/tasks', {
    method: 'POST',
    body: JSON.stringify({ intent }),
  })
}

export function approveTask(id, comment = '') {
  return request(`/tasks/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision: 'APPROVED', comment: comment || null }),
  })
}

export function rejectTask(id, comment = '') {
  return request(`/tasks/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ decision: 'REJECTED', comment: comment || null }),
  })
}

export function cancelTask(id) {
  return request(`/tasks/${id}/cancel`, { method: 'POST' })
}
