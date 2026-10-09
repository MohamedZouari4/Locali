// Timing of the startup intro, in milliseconds from the moment it starts. The canvas scene, the CSS
// animations (through the --t-* custom properties) and the sound all read these, so they stay in sync.

export const TIMELINES = {
  // Particles drift, swirl in and assemble into the mark, the name and tagline appear, then it dissolves.
  full: {
    assembleStart: 600,
    logoLock: 2300,
    nameStart: 2650,
    taglineStart: 3450,
    exitStart: 5300,
    exitDuration: 850,
  },
  // Reduced motion: no particles or camera moves, the brand is shown still for a moment.
  reduced: {
    assembleStart: 0,
    logoLock: 0,
    nameStart: 0,
    taglineStart: 0,
    exitStart: 1800,
    exitDuration: 400,
  },
  // Already played this session (e.g. after a reload): nothing to watch, only a loading state if needed.
  quiet: {
    assembleStart: 0,
    logoLock: 0,
    nameStart: 0,
    taglineStart: 0,
    exitStart: 0,
    exitDuration: 400,
  },
}

export const SKIPPED_EXIT_MS = 450

// In the quiet variant the loading state only shows once starting takes longer than this,
// so a fast start doesn't flash it.
export const QUIET_REVEAL_MS = 600
