import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiRequest } from './api'
import { AppContext } from './AppContext'
import { getWebSocketUrl } from './config'
import ControlPanel from './components/ControlPanel'
import Dashboard from './components/Dashboard'
import './App.css'

const MAX_HISTORY_SAMPLES = 200
const Viewer3D = lazy(() => import('./components/Viewer3D'))

function App() {
  const [connected, setConnected] = useState(false)
  const [connectionState, setConnectionState] = useState('connecting')
  const [latencyMs, setLatencyMs] = useState(null)
  const [robotInfo, setRobotInfo] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [jointAngles, setJointAngles] = useState([])
  const [linkStates, setLinkStates] = useState([])
  const [controlMode, setControlModeState] = useState('manual')
  const [telemetryHistory, setTelemetryHistory] = useState([])
  const [ikTarget, setIkTarget] = useState(null)
  const [safetyZones, setSafetyZones] = useState([])
  const [sidePanel, setSidePanel] = useState('controls')
  const [notice, setNotice] = useState(null)
  const wsRef = useRef(null)

  const handleMessage = useCallback((message) => {
    switch (message.type) {
      case 'robot_info':
        setRobotInfo(message.data)
        setJointAngles(new Array(message.data.num_joints).fill(0))
        break
      case 'telemetry':
      case 'state':
        setTelemetry(message.data)
        if (message.data.control_mode) setControlModeState(message.data.control_mode)
        if (message.data.joint_angles) setJointAngles(message.data.joint_angles)
        if (message.data.links) setLinkStates(message.data.links)
        setTelemetryHistory((history) => {
          const next = [...history, { ...message.data, clientTimestamp: Date.now() }]
          return next.slice(-MAX_HISTORY_SAMPLES)
        })
        break
      case 'ik_result':
        if (message.data?.success) {
          setJointAngles(message.data.joint_angles)
          setNotice({ type: 'success', text: 'IK target accepted.' })
        } else {
          setNotice({ type: 'error', text: 'The requested target is not reachable.' })
        }
        break
      case 'mode_changed':
        setControlModeState(message.data.mode)
        break
      case 'pong': {
        const sentAt = Number(message.request_id?.replace('heartbeat-', ''))
        if (Number.isFinite(sentAt)) setLatencyMs(Math.max(0, Date.now() - sentAt))
        break
      }
      case 'error':
        setNotice({ type: 'error', text: message.message })
        break
      default:
        break
    }
  }, [])

  useEffect(() => {
    let disposed = false
    let reconnectTimer
    let heartbeatTimer
    let retryDelay = 1000

    function connect() {
      if (disposed) return
      const socket = new WebSocket(getWebSocketUrl())
      wsRef.current = socket

      socket.onopen = () => {
        retryDelay = 1000
        setConnected(true)
        setConnectionState('connected')
        setNotice(null)
        heartbeatTimer = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              command: 'ping',
              request_id: `heartbeat-${Date.now()}`,
            }))
          }
        }, 10_000)
      }
      socket.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(event.data))
        } catch {
          setNotice({ type: 'error', text: 'Received an invalid telemetry message.' })
        }
      }
      socket.onerror = () => socket.close()
      socket.onclose = () => {
        window.clearInterval(heartbeatTimer)
        setConnected(false)
        setLatencyMs(null)
        setConnectionState(disposed ? 'offline' : 'reconnecting')
        if (wsRef.current === socket) wsRef.current = null
        if (!disposed) {
          reconnectTimer = window.setTimeout(connect, retryDelay)
          retryDelay = Math.min(retryDelay * 2, 10_000)
        }
      }
    }

    connect()
    apiRequest('/api/safety-zones').then(setSafetyZones).catch(() => setSafetyZones([]))
    apiRequest('/api/mode').then(({ mode }) => setControlModeState(mode)).catch(() => {})

    return () => {
      disposed = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(heartbeatTimer)
      const socket = wsRef.current
      wsRef.current = null
      if (socket) socket.close()
    }
  }, [handleMessage])

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(null), 4500)
    return () => window.clearTimeout(timer)
  }, [notice])

  const sendCommand = useCallback((command, data = {}) => {
    const socket = wsRef.current
    if (socket?.readyState !== WebSocket.OPEN) {
      setNotice({ type: 'error', text: 'The simulator is offline. Command not sent.' })
      return false
    }
    socket.send(JSON.stringify({ command, ...data }))
    return true
  }, [])

  const setJointAngle = useCallback((index, angle) => {
    sendCommand('set_single_joint', { joint_index: index, angle })
  }, [sendCommand])

  const setAllJoints = useCallback((angles) => {
    sendCommand('set_joints', { angles })
  }, [sendCommand])

  const moveToIK = useCallback((position) => {
    if (sendCommand('ik_move', { target_position: position })) setIkTarget(position)
  }, [sendCommand])

  const setControlMode = useCallback((mode) => {
    if (sendCommand('set_mode', { mode })) setControlModeState(mode)
  }, [sendCommand])

  const resetArm = useCallback(() => {
    if (sendCommand('reset')) {
      setTelemetryHistory([])
      setIkTarget(null)
      setNotice({ type: 'success', text: 'Robot reset and emergency stop released.' })
    }
  }, [sendCommand])

  const emergencyStop = useCallback(() => {
    if (sendCommand('emergency_stop')) {
      setNotice({ type: 'error', text: 'Emergency stop engaged. Reset to resume motion.' })
    }
  }, [sendCommand])

  const contextValue = useMemo(() => ({
    connected,
    connectionState,
    latencyMs,
    robotInfo,
    telemetry,
    jointAngles,
    linkStates,
    controlMode,
    telemetryHistory,
    ikTarget,
    safetyZones,
    setControlMode,
    setJointAngle,
    setAllJoints,
    moveToIK,
    resetArm,
    emergencyStop,
    setSafetyZones,
    setNotice,
  }), [
    connected, connectionState, controlMode, emergencyStop, ikTarget, jointAngles, latencyMs, linkStates,
    moveToIK, resetArm, robotInfo, safetyZones, setAllJoints, setControlMode,
    setJointAngle, telemetry, telemetryHistory,
  ])

  const emergencyStopped = Boolean(telemetry?.emergency_stopped)
  const safetyViolations = telemetry?.safety_violations || []

  return (
    <AppContext.Provider value={contextValue}>
      <div className="app">
        <header className="app-header">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32">
                <circle cx="16" cy="16" r="13" />
                <path d="M10 21v-7l6-4 5 3v7" />
                <circle cx="16" cy="10" r="2" />
              </svg>
            </div>
            <div>
              <h1>RoboArm AI</h1>
              <p>7-axis digital twin workspace</p>
            </div>
          </div>

          <div className="header-status">
            <div className="header-metric">
              <span>SIM TIME</span>
              <strong>{telemetry?.sim_time?.toFixed(1) || '0.0'} s</strong>
            </div>
            <div className="header-metric header-metric-wide">
              <span>CONTROL</span>
              <strong>{controlMode.toUpperCase()}</strong>
            </div>
            <div className={`connection-badge ${connected ? 'connected' : 'disconnected'}`}>
              <span className="connection-dot" />
              {connected
                ? `CONNECTED${latencyMs !== null ? ` · ${latencyMs} MS` : ''}`
                : connectionState.toUpperCase()}
            </div>
          </div>
        </header>

        {emergencyStopped && (
          <div className="estop-banner" role="alert">
            Emergency stop is engaged. Use Reset system to resume motion.
          </div>
        )}

        {safetyViolations.length > 0 && (
          <div className="safety-banner" role="alert">
            <strong>Safety boundary violation</strong>
            <span>{safetyViolations.map((violation) => violation.message).join(' · ')}</span>
          </div>
        )}

        <main className="app-main">
          <section className="viewer-container" aria-label="Interactive robot view">
            <Suspense fallback={<div className="viewer-loading">Loading 3D workspace&hellip;</div>}>
              <Viewer3D />
            </Suspense>
            <div className="viewer-kicker">LIVE DIGITAL TWIN</div>
            <div className="viewer-overlay-bottom">
              <div className="coordinate-readout">
                <span>END EFFECTOR / METERS</span>
                <strong>
                  {telemetry?.end_effector_pos
                    ?.map((value) => Number(value).toFixed(3))
                    .join(' · ') || '—'}
                </strong>
              </div>
              <div className="viewer-hint">Drag to orbit · Scroll to zoom</div>
            </div>
          </section>

          <aside className="side-panel" aria-label="Robot controls and analytics">
            <div className="panel-tabs" role="tablist">
              <button
                className={`panel-tab ${sidePanel === 'controls' ? 'active' : ''}`}
                onClick={() => setSidePanel('controls')}
                role="tab"
                aria-selected={sidePanel === 'controls'}
              >
                Controls
              </button>
              <button
                className={`panel-tab ${sidePanel === 'analytics' ? 'active' : ''}`}
                onClick={() => setSidePanel('analytics')}
                role="tab"
                aria-selected={sidePanel === 'analytics'}
              >
                Analytics
              </button>
            </div>
            <div className="panel-content">
              {sidePanel === 'controls' ? <ControlPanel /> : <Dashboard />}
            </div>
          </aside>
        </main>

        {notice && (
          <div className={`toast ${notice.type}`} role="status">
            {notice.text}
          </div>
        )}
      </div>
    </AppContext.Provider>
  )
}

export default App
