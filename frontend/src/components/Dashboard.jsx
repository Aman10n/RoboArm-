import { useMemo } from 'react'
import { useAppContext } from '../AppContext'

const COLORS = ['#36c2ff', '#8b7cff', '#ec6da5', '#55d6a4', '#f6b84a', '#ff776d', '#5dd5dc']

function MiniChart({ data, color }) {
  if (!data || data.length < 2) return <div className="chart-placeholder" />

  const minimum = Math.min(...data)
  const maximum = Math.max(...data)
  const range = maximum - minimum || 1
  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * 100
    const y = 34 - ((value - minimum) / range) * 30
    return `${x},${y}`
  }).join(' ')

  return (
    <svg className="mini-chart" viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden="true">
      <polygon points={`0,38 ${points} 100,38`} fill={color} opacity="0.12" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function Metric({ label, value, accent = false }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong className={accent ? 'accent' : ''}>{value}</strong>
    </div>
  )
}

export default function Dashboard() {
  const { connected, telemetry, telemetryHistory, robotInfo } = useAppContext()
  const numJoints = robotInfo?.num_joints || 7
  const jointLimits = robotInfo?.joint_limits || []

  const history = useMemo(() => {
    const series = { velocity: [], torque: [], endEffector: [[], [], []] }
    for (let joint = 0; joint < numJoints; joint += 1) {
      series.velocity[joint] = telemetryHistory.map((sample) => sample.joint_velocities?.[joint] || 0)
      series.torque[joint] = telemetryHistory.map((sample) => sample.joint_torques?.[joint] || 0)
    }
    for (let axis = 0; axis < 3; axis += 1) {
      series.endEffector[axis] = telemetryHistory.map((sample) => sample.end_effector_pos?.[axis] || 0)
    }
    return series
  }, [numJoints, telemetryHistory])

  return (
    <div className="dashboard">
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">TELEMETRY</span>
            <h2>System overview</h2>
          </div>
          <span className={`live-badge ${connected ? '' : 'offline'}`}>
            <i />{connected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
        <div className="metric-grid">
          <Metric label="Simulation time" value={`${telemetry?.sim_time?.toFixed(1) || '0.0'} s`} accent />
          <Metric label="Physics steps" value={(telemetry?.step_count || 0).toLocaleString()} />
          <Metric label="Samples buffered" value={telemetryHistory.length} />
          <Metric label="Stream rate" value="30 Hz" />
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">POSITION</span>
            <h2>Joint utilization</h2>
          </div>
          <span className="card-note">radians</span>
        </div>
        <div className="joint-bars">
          {Array.from({ length: numJoints }, (_, index) => {
            const value = telemetry?.joint_angles?.[index] || 0
            const limit = jointLimits[index] || { lower: -Math.PI, upper: Math.PI }
            const utilization = ((value - limit.lower) / (limit.upper - limit.lower)) * 100
            return (
              <div className="joint-bar-row" key={index}>
                <div className="joint-bar-label">
                  <span>A{index + 1}</span>
                  <strong>{value.toFixed(3)}</strong>
                </div>
                <div className="joint-bar-track">
                  <i style={{ width: `${Math.max(0, Math.min(100, utilization))}%`, background: COLORS[index] }} />
                </div>
              </div>
            )
          })}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">MOTION</span>
            <h2>Joint velocity</h2>
          </div>
          <span className="card-note">rad/s</span>
        </div>
        <div className="series-list">
          {Array.from({ length: Math.min(numJoints, 4) }, (_, index) => (
            <div className="series-row" key={index}>
              <div className="series-heading">
                <span>A{index + 1}</span>
                <strong style={{ color: COLORS[index] }}>
                  {telemetry?.joint_velocities?.[index]?.toFixed(3) || '0.000'}
                </strong>
              </div>
              <MiniChart data={history.velocity[index]} color={COLORS[index]} />
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">LOAD</span>
            <h2>Joint torque</h2>
          </div>
          <span className="card-note">N·m</span>
        </div>
        <div className="series-list">
          {Array.from({ length: Math.min(numJoints, 4) }, (_, index) => (
            <div className="series-row" key={index}>
              <div className="series-heading">
                <span>A{index + 1}</span>
                <strong style={{ color: COLORS[index] }}>
                  {telemetry?.joint_torques?.[index]?.toFixed(2) || '0.00'}
                </strong>
              </div>
              <MiniChart data={history.torque[index]} color={COLORS[index]} />
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">TOOL CENTER POINT</span>
            <h2>End-effector trace</h2>
          </div>
          <span className="card-note">meters</span>
        </div>
        <div className="series-list">
          {['X', 'Y', 'Z'].map((axis, index) => (
            <div className="series-row" key={axis}>
              <div className="series-heading">
                <span>{axis}</span>
                <strong style={{ color: COLORS[index] }}>
                  {telemetry?.end_effector_pos?.[index]?.toFixed(4) || '0.0000'}
                </strong>
              </div>
              <MiniChart data={history.endEffector[index]} color={COLORS[index]} />
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
