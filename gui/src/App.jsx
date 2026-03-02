import { useState, useEffect, useCallback } from 'react'
import { fetchTasks, fetchTask, createTask, approveTask, rejectTask } from './api'
import TaskList from './components/TaskList'
import TaskDetail from './components/TaskDetail'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [selectedTask, setSelectedTask] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [listError, setListError] = useState(null)

  // Load the task list
  const loadTasks = useCallback(async () => {
    setLoadingList(true)
    setListError(null)
    try {
      const data = await fetchTasks()
      setTasks(data)
    } catch (err) {
      setListError(err.message)
    } finally {
      setLoadingList(false)
    }
  }, [])

  // Load a single task's full detail
  const loadTask = useCallback(async (id) => {
    setLoadingDetail(true)
    try {
      const data = await fetchTask(id)
      setSelectedTask(data)
    } catch (err) {
      console.error('Failed to load task detail:', err)
    } finally {
      setLoadingDetail(false)
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

  // Initial load
  useEffect(() => { loadTasks() }, [loadTasks])

  return (
    <>
      <header className="app-header">
        <span className="dot" />
        <h1>LLMOS</h1>
      </header>

      <div className="app-body">
        <TaskList
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelect={selectTask}
          onSubmit={handleSubmit}
          onRefresh={loadTasks}
          loading={loadingList}
          error={listError}
        />

        {selectedTask ? (
          <TaskDetail
            task={selectedTask}
            loading={loadingDetail}
            onRefresh={() => loadTask(selectedTaskId)}
            onApprove={handleApprove}
            onReject={handleReject}
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
