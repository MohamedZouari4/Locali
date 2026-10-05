// Sidebar panel for background jobs: a progress bar for each running job, a Cancel button while a
// job is active, and the outcome for a few seconds after it ends. Hidden when there are no jobs.

import { isActive } from '../../hooks/useJobs'
import { Icon } from '../Icon'

const titles = { demo: 'Demo job', ingest: 'Indexing files', forget_folder: 'Removing a folder' }
const outcomes = { queued: 'Waiting', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' }

function JobRow({ job, onCancel }) {
  const title = titles[job.kind] ?? job.kind
  const percent = job.progress_total ? Math.min(100, Math.round((100 * (job.progress_current ?? 0)) / job.progress_total)) : null
  const running = job.state === 'running'
  let status = outcomes[job.state]
  if (running) status = job.cancel_requested ? 'Cancelling…' : percent === null ? 'Running' : `${percent}%`

  return (
    <li className={`job job--${job.state}`}>
      <div className="job__header">
        <span className="job__title">{title}</span>
        <span className="job__status">{status}</span>
        {isActive(job) && !job.cancel_requested && (
          <button className="small-icon small-icon--danger" type="button" onClick={() => onCancel(job.id)} aria-label={`Cancel ${title}`} title="Cancel">
            <Icon name="close" size={14} />
          </button>
        )}
      </div>
      {running && percent !== null && (
        <div className="job__bar" role="progressbar" aria-label={title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span className="job__bar-fill" style={{ width: `${percent}%` }} />
        </div>
      )}
      {running && job.progress_message && <small className="job__message">{job.progress_message}</small>}
      {job.state === 'failed' && job.error && <small className="job__message job__message--error">{job.error}</small>}
    </li>
  )
}

export function JobsPanel({ jobs, onCancel }) {
  if (jobs.length === 0) return null

  return (
    <section className="jobs" aria-label="Background tasks">
      <h2 className="group-label">Background tasks</h2>
      <ul className="jobs__list">
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} onCancel={onCancel} />
        ))}
      </ul>
    </section>
  )
}
