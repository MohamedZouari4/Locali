// Banner above the chat listing the problems the health checks found, each with what it means and
// how to fix it, plus a button to check again. Hidden when everything is fine.

import { Icon } from '../Icon'

export function HealthBanner({ report, onCheckAgain }) {
  const problems = report?.checks.filter((check) => check.status === 'error' || check.status === 'warning') ?? []
  if (problems.length === 0) return null

  return (
    <section className={`health-banner health-banner--${report.status}`} aria-label="Problems found" role="status">
      <ul className="health-banner__list">
        {problems.map((check) => (
          <li key={check.id} className={`health-banner__item health-banner__item--${check.status}`}>
            <Icon name="alert" size={17} />
            <div>
              <strong>{check.title}</strong>
              {check.detail && <span className="health-banner__detail"> {check.detail}</span>}
              {check.fix && <p className="health-banner__fix">{check.fix}</p>}
            </div>
          </li>
        ))}
      </ul>
      <button className="health-banner__retry" type="button" onClick={onCheckAgain}>
        <Icon name="retry" size={14} /> Check again
      </button>
    </section>
  )
}
