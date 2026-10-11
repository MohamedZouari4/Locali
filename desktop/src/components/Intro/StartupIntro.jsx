// Startup intro shown over the app once per launch: particles assemble into the Locali mark, the name
// and tagline appear with a synthesized sound logo, then it dissolves into the chat screen.
// It always plays in full: there are no controls and no key skips it. If the local services are still
// starting when it ends, it becomes a loading state until they're ready. It plays on every load, and
// reduced motion gets a short, still version. Timings are in timeline.js.

import { useCallback, useEffect, useRef, useState } from 'react'
import { createIntroAudio } from './introAudio'
import { startParticleScene } from './logoParticles'
import { DOT, MARK_COLORS, MARK_VIEWBOX, STEM, TILE } from './mark'
import { TIMELINES } from './timeline'
import './StartupIntro.css'

const NAME = 'Locali'
const TAGLINE = 'Private AI for your files'

function chooseVariant() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'reduced' : 'full'
}

// The app icon (electron/icons/icon.svg) with a band of light that sweeps across it once.
function IntroMark() {
  return (
    <svg className="startup-intro__mark" viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`} aria-hidden="true">
      <defs>
        <linearGradient id="intro-tile" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={MARK_COLORS.tileTop} />
          <stop offset="1" stopColor={MARK_COLORS.tileBottom} />
        </linearGradient>
        <linearGradient id="intro-shine" x1="0" y1="0" x2="1" y2="0.4">
          <stop offset="0.38" stopColor="#FFFFFF" stopOpacity="0" />
          <stop offset="0.5" stopColor="#FFFFFF" stopOpacity="0.35" />
          <stop offset="0.62" stopColor="#FFFFFF" stopOpacity="0" />
        </linearGradient>
        <clipPath id="intro-tile-clip">
          <rect x={TILE.x} y={TILE.y} width={TILE.size} height={TILE.size} rx={TILE.radius} />
        </clipPath>
      </defs>
      <rect x={TILE.x} y={TILE.y} width={TILE.size} height={TILE.size} rx={TILE.radius} fill="url(#intro-tile)" />
      <path d={STEM.path} fill="none" stroke={MARK_COLORS.stem} strokeWidth={STEM.width} strokeLinecap="round" />
      <circle cx={DOT.cx} cy={DOT.cy} r={DOT.r} fill={MARK_COLORS.dot} />
      <g clipPath="url(#intro-tile-clip)">
        <rect className="startup-intro__shine" width={MARK_VIEWBOX} height={MARK_VIEWBOX} fill="url(#intro-shine)" />
      </g>
    </svg>
  )
}

export function StartupIntro({ ready, onDone }) {
  const [variant] = useState(chooseVariant)
  const timeline = TIMELINES[variant]
  const [introOver, setIntroOver] = useState(false)
  const canvasRef = useRef(null)
  const logoRef = useRef(null)
  const audioRef = useRef(null)
  const startedAt = useRef(0)
  const getElapsed = useCallback(() => performance.now() - startedAt.current, [])

  const exiting = introOver && ready
  const waiting = introOver && !ready
  const exitMs = timeline.exitDuration

  // Start the particles, the sound and the end-of-intro timer from the same moment.
  useEffect(() => {
    startedAt.current = performance.now()

    const stopScene = variant === 'full'
      ? startParticleScene(canvasRef.current, logoRef.current, getElapsed, timeline)
      : () => {}
    // Electron lets the sound start on its own; where autoplay is blocked (a plain browser), it stays silent.
    const audio = createIntroAudio(timeline, { full: variant === 'full', getElapsed })
    audioRef.current = audio
    audio?.start()
    const timer = setTimeout(() => setIntroOver(true), timeline.exitStart)

    return () => {
      stopScene()
      clearTimeout(timer)
      audioRef.current?.stop(0.9) // lets the outro cue ring out while the app appears
      audioRef.current = null
    }
  }, [variant, timeline, getElapsed])

  // Dissolve into the app once the animation is over and the services are ready.
  useEffect(() => {
    if (!exiting) return undefined
    audioRef.current?.playOutro()
    const timer = setTimeout(onDone, exitMs)
    return () => clearTimeout(timer)
  }, [exiting, exitMs, onDone])

  const classes = [
    'startup-intro',
    `startup-intro--${variant}`,
    variant !== 'full' && 'is-static',
    exiting && 'is-exiting',
  ].filter(Boolean).join(' ')

  return (
    <section
      className={classes}
      aria-label="Starting Locali"
      style={{
        '--t-logo': `${timeline.logoLock}ms`,
        '--t-name': `${timeline.nameStart}ms`,
        '--t-tagline': `${timeline.taglineStart}ms`,
        '--t-total': `${timeline.exitStart + timeline.exitDuration}ms`,
        '--t-exit': `${exitMs}ms`,
      }}
    >
      <div className="startup-intro__atmosphere" aria-hidden="true" />
      <canvas ref={canvasRef} className="startup-intro__canvas" aria-hidden="true" />

      <div className="startup-intro__stage">
        <div ref={logoRef} className="startup-intro__logo">
          <div className="startup-intro__bloom" aria-hidden="true" />
          <div className="startup-intro__flare" aria-hidden="true" />
          <IntroMark />
        </div>
        <h1 className="startup-intro__name" aria-label={NAME}>
          {[...NAME].map((letter, index) => (
            <span key={index} className="startup-intro__letter" style={{ '--i': index }} aria-hidden="true">
              {letter}
            </span>
          ))}
        </h1>
        <p className="startup-intro__tagline">{TAGLINE}</p>

        {waiting && (
          <div className="startup-intro__status" role="status">
            <span>Starting local services…</span>
            <span className="startup-intro__progress" aria-hidden="true" />
          </div>
        )}
      </div>

    </section>
  )
}
