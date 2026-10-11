// Sidebar project switcher: a button showing the current project that opens a menu of projects, with
// "New project…" at the bottom, and a settings button beside it. Built as a listbox rather than a native
// <select>, so the menu matches the rest of the app. Keyboard: Enter, Space or the arrow keys open it;
// arrows move, Enter picks, Esc or a click outside closes it.

import { useEffect, useRef, useState } from 'react'
import { Icon } from '../Icon'

export function ProjectSwitcher({ projects, projectId, onSelect, onCreate, onSettings }) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0) // index of the highlighted option; projects.length is "New project…"
  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const current = projects.find((project) => project.id === projectId)
  const optionCount = projects.length + 1

  useEffect(() => {
    if (!open) return undefined
    const closeOnOutsideClick = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [open])

  const openMenu = () => {
    setActive(Math.max(0, projects.findIndex((project) => project.id === projectId)))
    setOpen(true)
  }

  const close = () => {
    setOpen(false)
    buttonRef.current?.focus()
  }

  const choose = (index) => {
    close()
    if (index === projects.length) onCreate()
    else onSelect(projects[index].id)
  }

  const handleKeyDown = (event) => {
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
        event.preventDefault()
        openMenu()
      }
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => (index + (event.key === 'ArrowDown' ? 1 : optionCount - 1)) % optionCount)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(active)
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  return (
    <div className="project-switcher" ref={rootRef}>
      <button
        ref={buttonRef}
        className="project-switcher__button"
        type="button"
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={handleKeyDown}
        disabled={!projectId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls="project-menu"
        aria-activedescendant={open ? `project-option-${active}` : undefined}
        aria-label={`Project: ${current?.name ?? 'loading'}`}
      >
        <Icon name="folder" size={15} />
        <span className="project-switcher__name">{current?.name ?? 'Loading…'}</span>
        <Icon name="chevronDown" size={14} />
      </button>
      <button className="small-icon project-switcher__settings" type="button" onClick={onSettings} disabled={!projectId} aria-label="Project settings" title="Project settings">
        <Icon name="settings" size={15} />
      </button>

      {open && (
        <ul className="project-menu" id="project-menu" role="listbox" aria-label="Projects">
          {projects.map((project, index) => (
            <li
              key={project.id}
              id={`project-option-${index}`}
              role="option"
              aria-selected={project.id === projectId}
              className={`project-menu__option ${index === active ? 'project-menu__option--active' : ''}`}
              onPointerEnter={() => setActive(index)}
              onClick={() => choose(index)}
            >
              <span className="project-menu__name">{project.name}</span>
              {project.id === projectId && <Icon name="check" size={14} />}
            </li>
          ))}
          <li
            id={`project-option-${projects.length}`}
            role="option"
            aria-selected={false}
            className={`project-menu__option project-menu__option--new ${active === projects.length ? 'project-menu__option--active' : ''}`}
            onPointerEnter={() => setActive(projects.length)}
            onClick={() => choose(projects.length)}
          >
            <Icon name="plus" size={14} />
            <span className="project-menu__name">New project…</span>
          </li>
        </ul>
      )}
    </div>
  )
}
