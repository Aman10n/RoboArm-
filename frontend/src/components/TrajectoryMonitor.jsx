import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api'
import { useAppContext } from '../AppContext'

const EMPTY_STATUS = { state: 'idle', progress: 0, elapsed: 0, duration: 0 }

export default function TrajectoryMonitor() {
  const { connected, setNotice } = useAppContext()
  const [status, setStatus] = useState(EMPTY_STATUS)

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await apiRequest('/api/trajectory/status'))
    } catch {
      setStatus(EMPTY_STATUS)
    }
  }, [])

  useEffect(() => {
    if (!connected) return undefined
    const timer = window.setInterval(refreshStatus, 750)
    return () => window.clearInterval(timer)
  }, [connected, refreshStatus])

  const stopTrajectory = useCallback(async () => {
    try {
      await apiRequest('/api/trajectory/stop', { method: 'POST' })
      await refreshStatus()
      setNotice({ type: 'success', text: 'Trajectory stopped safely.' })
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [refreshStatus, setNotice])

  const visibleStatus = connected ? status : EMPTY_STATUS
  const progress = Math.round((visibleStatus.progress || 0) * 100)
  const stateLabel = visibleStatus.state === 'idle' ? 'No trajectory loaded' : visibleStatus.state

  return (
    <section className="card trajectory-card">
      <div className="card-header">
        <div>
          <span className="eyebrow">MOTION PROGRAM</span>
          <h2>Trajectory status</h2>
        </div>
        <span className={`trajectory-state ${visibleStatus.state}`}>{stateLabel}</span>
      </div>
      <div className="trajectory-progress" aria-label={`Trajectory ${progress}% complete`}>
        <i style={{ width: `${progress}%` }} />
      </div>
      <div className="trajectory-meta">
        <span>{progress}% complete</span>
        <span>{(visibleStatus.elapsed || 0).toFixed(1)} / {(visibleStatus.duration || 0).toFixed(1)} s</span>
      </div>
      {visibleStatus.failure_reason && <p className="trajectory-error">{visibleStatus.failure_reason}</p>}
      {visibleStatus.state === 'executing' && (
        <button className="btn btn-secondary btn-block" onClick={stopTrajectory}>
          Stop trajectory
        </button>
      )}
    </section>
  )
}
