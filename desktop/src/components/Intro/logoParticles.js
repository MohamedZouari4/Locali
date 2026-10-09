// Canvas scene for the startup intro: slow drifting dust with depth, and a cloud of particles that
// swirls in and assembles into the Locali mark, landing exactly where the SVG logo then fades in.
// Time comes from getElapsed() (ms since the intro started), the same clock the sound uses.

import { DOT, MARK_COLORS, MARK_VIEWBOX, STEM, TILE } from './mark'

const MAX_PIXEL_RATIO = 2
const DUST_COUNT = 110
const FOCAL_LENGTH = 700 // perspective, in CSS pixels
const FADE_IN_MS = 1000
const HANDOFF_MS = 400 // particles fade out while the SVG logo fades in
const DUST_RGB = '190 225 205'

const clamp01 = (x) => Math.min(1, Math.max(0, x))
const easeInOutCubic = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2)

function drawMark(context) {
  const tile = context.createLinearGradient(0, TILE.y, 0, TILE.y + TILE.size)
  tile.addColorStop(0, MARK_COLORS.tileTop)
  tile.addColorStop(1, MARK_COLORS.tileBottom)
  context.fillStyle = tile
  context.beginPath()
  context.roundRect(TILE.x, TILE.y, TILE.size, TILE.size, TILE.radius)
  context.fill()

  context.strokeStyle = MARK_COLORS.stem
  context.lineWidth = STEM.width
  context.lineCap = 'round'
  context.stroke(new Path2D(STEM.path))

  context.fillStyle = MARK_COLORS.dot
  context.beginPath()
  context.arc(DOT.cx, DOT.cy, DOT.r, 0, Math.PI * 2)
  context.fill()
}

// Draws the mark `size` CSS pixels wide and returns a point, with its colour, for each filled grid cell.
function sampleMark(size) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = Math.max(1, Math.ceil(size))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  context.scale(canvas.width / MARK_VIEWBOX, canvas.height / MARK_VIEWBOX)
  drawMark(context)

  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  const step = Math.max(3, Math.round(size / 46))
  const points = []
  for (let y = Math.floor(step / 2); y < canvas.height; y += step) {
    for (let x = Math.floor(step / 2); x < canvas.width; x += step) {
      const i = (y * canvas.width + x) * 4
      if (data[i + 3] > 128) points.push({ x, y, color: `rgb(${data[i]} ${data[i + 1]} ${data[i + 2]})` })
    }
  }
  return { points, step }
}

// A soft round dot, drawn once and stamped for every dust particle.
function makeGlowSprite() {
  const sprite = document.createElement('canvas')
  sprite.width = sprite.height = 32
  const context = sprite.getContext('2d')
  const glow = context.createRadialGradient(16, 16, 0, 16, 16, 16)
  glow.addColorStop(0, `rgb(${DUST_RGB})`)
  glow.addColorStop(0.35, `rgb(${DUST_RGB} / 35%)`)
  glow.addColorStop(1, `rgb(${DUST_RGB} / 0%)`)
  context.fillStyle = glow
  context.fillRect(0, 0, 32, 32)
  return sprite
}

function makeDust() {
  const depth = Math.random() // 0 far, 1 near
  return {
    x: Math.random(),
    y: Math.random(),
    depth,
    rise: (0.004 + depth * 0.012) / 1000, // screen heights per ms
    phase: Math.random() * Math.PI * 2,
    radius: 1.5 + depth * 4.5,
  }
}

export function startParticleScene(canvas, logoElement, getElapsed, timeline) {
  const context = canvas.getContext('2d')
  const sprite = makeGlowSprite()
  const dust = Array.from({ length: DUST_COUNT }, makeDust)
  const totalMs = timeline.exitStart + timeline.exitDuration
  let width = 0
  let height = 0
  let center = { x: 0, y: 0 }
  let particleSize = 2
  let particles = []
  let frame = 0

  function layout() {
    const bounds = canvas.getBoundingClientRect()
    const logo = logoElement.getBoundingClientRect()
    const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)
    width = bounds.width
    height = bounds.height
    canvas.width = Math.round(width * ratio)
    canvas.height = Math.round(height * ratio)
    context.setTransform(ratio, 0, 0, ratio, 0, 0)

    const left = logo.left - bounds.left
    const top = logo.top - bounds.top
    center = { x: left + logo.width / 2, y: top + logo.height / 2 }
    const { points, step } = sampleMark(logo.width)
    const spread = Math.max(width, height)
    particleSize = step * 0.82
    particles = points
      .map((point) => {
        const angle = Math.random() * Math.PI * 2
        const distance = spread * (0.3 + Math.random() * 0.6)
        const delay = timeline.assembleStart + Math.random() * 520
        return {
          targetX: left + point.x,
          targetY: top + point.y,
          startX: center.x + Math.cos(angle) * distance,
          startY: center.y + Math.sin(angle) * distance * 0.7,
          startZ: -250 + Math.random() * 1500,
          swirl: 0.8 + Math.random() * 0.8, // radians still to turn when it sets off
          delay,
          duration: timeline.logoLock - delay,
          phase: Math.random() * Math.PI * 2,
          color: point.color,
        }
      })
      .sort((a, b) => (a.color < b.color ? -1 : 1)) // fewer fillStyle changes per frame
  }

  function drawDust(t, fadeIn) {
    const push = 1 + 0.06 * Math.min(1, t / totalMs) // slow camera push-in
    context.globalCompositeOperation = 'lighter'
    for (const mote of dust) {
      const y = (((mote.y - t * mote.rise) % 1) + 1) % 1
      const scale = push * (1 + mote.depth * 0.04)
      const x = width / 2 + (mote.x * width - width / 2) * scale + Math.sin(t / 2400 + mote.phase) * 8 * mote.depth
      const screenY = height / 2 + (y * height - height / 2) * scale
      const twinkle = 0.65 + 0.35 * Math.sin(t / 700 + mote.phase)
      const size = mote.radius * 2
      context.globalAlpha = (0.12 + mote.depth * 0.4) * twinkle * fadeIn
      context.drawImage(sprite, x - size / 2, screenY - size / 2, size, size)
    }
  }

  function drawLogoParticles(t, fadeIn) {
    const handoff = 1 - clamp01((t - timeline.logoLock) / HANDOFF_MS)
    if (handoff <= 0) return
    context.globalCompositeOperation = 'source-over'
    let color = ''
    for (const p of particles) {
      const eased = easeInOutCubic(clamp01((t - p.delay) / p.duration))
      const remaining = 1 - eased
      // Fly from the start point to the target while turning around the logo's centre and coming forward.
      const drift = remaining * Math.sin(t / 900 + p.phase) * 6
      const x = p.startX + (p.targetX - p.startX) * eased - center.x
      const y = p.startY + (p.targetY - p.startY) * eased - center.y + drift
      const angle = p.swirl * remaining ** 1.5
      const cos = Math.cos(angle)
      const sin = Math.sin(angle)
      const perspective = FOCAL_LENGTH / (FOCAL_LENGTH + p.startZ * remaining)
      const size = particleSize * perspective

      context.globalAlpha = fadeIn * handoff * (0.35 + 0.65 * clamp01(eased * 1.6))
      if (p.color !== color) {
        color = p.color
        context.fillStyle = color
      }
      context.fillRect(
        center.x + (x * cos - y * sin) * perspective - size / 2,
        center.y + (x * sin + y * cos) * perspective - size / 2,
        size,
        size,
      )
    }
  }

  function draw() {
    const t = getElapsed()
    const fadeIn = clamp01(t / FADE_IN_MS)
    const assembling = t > timeline.assembleStart && t < timeline.logoLock + HANDOFF_MS

    // While the particles fly, clear only partly so they leave short motion trails.
    context.globalCompositeOperation = 'destination-out'
    context.globalAlpha = assembling ? 0.42 : 1
    context.fillRect(0, 0, width, height)

    drawDust(t, fadeIn)
    drawLogoParticles(t, fadeIn)
    frame = requestAnimationFrame(draw)
  }

  layout()
  const observer = new ResizeObserver(layout)
  observer.observe(canvas)
  frame = requestAnimationFrame(draw)

  return () => {
    cancelAnimationFrame(frame)
    observer.disconnect()
  }
}
