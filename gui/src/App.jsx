import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchTasks, fetchTask, createTask, approveTask, rejectTask, cancelTask } from './api'
import TaskList from './components/TaskList'
import TaskDetail from './components/TaskDetail'

const TERMINAL_STATES = new Set(['SUCCESS', 'FAILED', 'CANCELLED'])

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [selectedTask, setSelectedTask] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [listError, setListError] = useState(null)

  // Refs to avoid stale closures in intervals
  const selectedTaskIdRef = useRef(null)
  const selectedTaskRef = useRef(null)
  selectedTaskIdRef.current = selectedTaskId
  selectedTaskRef.current = selectedTask

  // Load the task list (silent = skip loading spinner for background polls)
  const loadTasks = useCallback(async (silent = false) => {
    if (!silent) setLoadingList(true)
    setListError(null)
    try {
      const data = await fetchTasks()
      setTasks(data)
    } catch (err) {
      setListError(err.message)
    } finally {
      if (!silent) setLoadingList(false)
    }
  }, [])

  // Load a single task's full detail
  const loadTask = useCallback(async (id) => {
    try {
      const data = await fetchTask(id)
      setSelectedTask(data)
    } catch (err) {
      console.error('Failed to load task detail:', err)
    }
  }, [])

  // Select a task (and load its detail)
  const selectTask = useCallback((id) => {
    setSelectedTaskId(id)
    loadTask(id)
  }, [loadTask])

  // Submit a new task
  const handleSubmit = useCallback(async (intent) => {
    const newTask = await createTask(intent)
    await loadTasks()
    selectTask(newTask.id)
  }, [loadTasks, selectTask])

  // Approve the awaiting task
  const handleApprove = useCallback(async (comment) => {
    if (!selectedTaskId) return
    await approveTask(selectedTaskId, comment)
    loadTask(selectedTaskId)
    loadTasks()
  }, [selectedTaskId, loadTask, loadTasks])

  // Reject the awaiting task
  const handleReject = useCallback(async (comment) => {
    if (!selectedTaskId) return
    await rejectTask(selectedTaskId, comment)
    loadTask(selectedTaskId)
    loadTasks()
  }, [selectedTaskId, loadTask, loadTasks])

  // Kill a running/pending task
  const handleCancel = useCallback(async () => {
    if (!selectedTaskId) return
    await cancelTask(selectedTaskId)
    loadTask(selectedTaskId)
    loadTasks()
  }, [selectedTaskId, loadTask, loadTasks])

  // Initial load
  useEffect(() => { loadTasks() }, [loadTasks])

  // Poll task list every 3s
  useEffect(() => {
    const id = setInterval(() => loadTasks(true), 3000)
    return () => clearInterval(id)
  }, [loadTasks])

  // Poll selected task detail every 2s, but only while it's in an active state
  useEffect(() => {
    const id = setInterval(() => {
      const taskId = selectedTaskIdRef.current
      const task = selectedTaskRef.current
      if (!taskId) return
      if (task && TERMINAL_STATES.has(task.state)) return
      loadTask(taskId)
    }, 2000)
    return () => clearInterval(id)
  }, [loadTask])

  return (
    <>
      <header className="app-header">
        <span className="dot" />
        <h1>ShellMind</h1>
      </header>

      <div className="app-body">
        <TaskList
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelect={selectTask}
          onSubmit={handleSubmit}
          loading={loadingList}
          error={listError}
        />

        {selectedTask ? (
          <TaskDetail
            task={selectedTask}
            onApprove={handleApprove}
            onReject={handleReject}
            onCancel={handleCancel}
          />
        ) : (
          <div className="no-task-selected">
            Select a task to see details
          </div>
        )}
      </div>
    </>
  )
}
