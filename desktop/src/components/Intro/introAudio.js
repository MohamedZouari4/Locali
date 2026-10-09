// Sound for the startup intro, synthesized with the Web Audio API so there are no audio files to load
// or license: a low ambient pad, a whoosh into the logo reveal, a soft impact, a four-note chime as the
// audio logo, and a gentle outro as the intro dissolves. Everything goes through a shared reverb, a
// compressor and a quiet master level. Times come from timeline.js, against the same clock as the visuals.

const MASTER_LEVEL = 0.3
const RESUME_TIMEOUT_MS = 200 // resume() never settles while autoplay is blocked

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function makeNoise(context, seconds) {
  const buffer = context.createBuffer(1, Math.floor(context.sampleRate * seconds), context.sampleRate)
  const data = buffer.getChannelData(0)
  for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1
  return buffer
}

// Decaying stereo noise: the impulse response of a soft, wide room.
function makeImpulse(context, seconds, decay) {
  const length = Math.floor(context.sampleRate * seconds)
  const buffer = context.createBuffer(2, length, context.sampleRate)
  for (let channel = 0; channel < 2; channel += 1) {
    const data = buffer.getChannelData(channel)
    for (let i = 0; i < length; i += 1) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** decay
  }
  return buffer
}

// Returns null when the Web Audio API isn't available; the intro then simply plays silently.
export function createIntroAudio(timeline, { full, getElapsed }) {
  const AudioContextClass = window.AudioContext ?? window.webkitAudioContext
  if (!AudioContextClass) return null
  let context
  try {
    context = new AudioContextClass({ latencyHint: 'playback' })
  } catch {
    return null
  }

  const master = context.createGain()
  master.gain.value = MASTER_LEVEL
  const compressor = context.createDynamicsCompressor()
  compressor.threshold.value = -18
  compressor.ratio.value = 3
  master.connect(compressor).connect(context.destination)

  const reverb = context.createConvolver()
  reverb.buffer = makeImpulse(context, 2.8, 2.6)
  const reverbReturn = context.createGain()
  reverbReturn.gain.value = 0.5
  reverb.connect(reverbReturn).connect(master)

  const noise = makeNoise(context, 2)
  let started = false
  let closed = false

  // Connects `node` to the master with `dry` level and to the reverb with `wet` level.
  function route(node, dry, wet) {
    const dryGain = context.createGain()
    dryGain.gain.value = dry
    node.connect(dryGain).connect(master)
    const wetGain = context.createGain()
    wetGain.gain.value = wet
    node.connect(wetGain).connect(reverb)
  }

  function noiseSource(start, stop) {
    const source = context.createBufferSource()
    source.buffer = noise
    source.loop = true
    source.start(start)
    source.stop(stop)
    return source
  }

  // Low, slowly opening pad (A and E across three octaves) with a breath of air on top.
  function ambience(start, lock, end) {
    const pad = context.createGain()
    pad.gain.setValueAtTime(0, start)
    pad.gain.linearRampToValueAtTime(0.45, start + 1.6)
    pad.gain.setValueAtTime(0.45, Math.max(start + 1.6, end - 1.4))
    pad.gain.linearRampToValueAtTime(0, end)
    const filter = context.createBiquadFilter()
    filter.type = 'lowpass'
    filter.Q.value = 0.7
    filter.frequency.setValueAtTime(180, start)
    filter.frequency.exponentialRampToValueAtTime(1400, Math.max(start + 0.5, lock))
    filter.frequency.exponentialRampToValueAtTime(600, end)
    filter.connect(pad)
    route(pad, 0.8, 0.4)

    for (const frequency of [55, 82.41, 110, 164.81]) {
      for (const detune of [-7, 7]) {
        const oscillator = context.createOscillator()
        oscillator.type = 'sawtooth'
        oscillator.frequency.value = frequency
        oscillator.detune.value = detune
        const level = context.createGain()
        level.gain.value = 0.08
        oscillator.connect(level).connect(filter)
        oscillator.start(start)
        oscillator.stop(end + 0.1)
      }
    }

    const air = context.createBiquadFilter()
    air.type = 'bandpass'
    air.frequency.value = 5500
    air.Q.value = 0.6
    const airLevel = context.createGain()
    airLevel.gain.setValueAtTime(0, start)
    airLevel.gain.linearRampToValueAtTime(0.03, start + 1.2)
    airLevel.gain.linearRampToValueAtTime(0, end)
    noiseSource(start, end + 0.1).connect(air).connect(airLevel)
    route(airLevel, 0.6, 0.6)
  }

  // Filtered noise that sweeps up and across the stereo field, peaking as the logo locks in.
  function whoosh(start, peak) {
    const filter = context.createBiquadFilter()
    filter.type = 'bandpass'
    filter.Q.value = 1.1
    filter.frequency.setValueAtTime(250, start)
    filter.frequency.exponentialRampToValueAtTime(2800, peak)
    filter.frequency.exponentialRampToValueAtTime(600, peak + 0.6)
    const level = context.createGain()
    level.gain.setValueAtTime(0.0001, start)
    level.gain.exponentialRampToValueAtTime(0.5, peak - 0.03)
    level.gain.exponentialRampToValueAtTime(0.0001, peak + 0.7)
    const pan = context.createStereoPanner()
    pan.pan.setValueAtTime(-0.6, start)
    pan.pan.linearRampToValueAtTime(0.4, peak)
    pan.pan.linearRampToValueAtTime(0, peak + 0.5)
    noiseSource(start, peak + 0.8).connect(filter).connect(level).connect(pan)
    route(pan, 0.7, 0.5)
  }

  // A low sine thump that drops in pitch, with a little high air.
  function impact(start) {
    const oscillator = context.createOscillator()
    oscillator.frequency.setValueAtTime(120, start)
    oscillator.frequency.exponentialRampToValueAtTime(42, start + 0.35)
    const level = context.createGain()
    level.gain.setValueAtTime(0.0001, start)
    level.gain.exponentialRampToValueAtTime(0.7, start + 0.012)
    level.gain.exponentialRampToValueAtTime(0.0001, start + 0.9)
    oscillator.connect(level)
    oscillator.start(start)
    oscillator.stop(start + 1)
    route(level, 0.9, 0.15)

    const shimmer = context.createBiquadFilter()
    shimmer.type = 'highpass'
    shimmer.frequency.value = 3500
    const shimmerLevel = context.createGain()
    shimmerLevel.gain.setValueAtTime(0.0001, start)
    shimmerLevel.gain.exponentialRampToValueAtTime(0.08, start + 0.01)
    shimmerLevel.gain.exponentialRampToValueAtTime(0.0001, start + 0.3)
    noiseSource(start, start + 0.35).connect(shimmer).connect(shimmerLevel)
    route(shimmerLevel, 0.3, 0.9)
  }

  // A soft bell: a few sine partials that each fade on their own, the higher ones sooner.
  function bell(frequency, start, level, decay) {
    for (const [ratio, amount] of [[1, 1], [2.01, 0.32], [3, 0.12], [4.2, 0.05]]) {
      const oscillator = context.createOscillator()
      oscillator.frequency.value = frequency * ratio
      const gain = context.createGain()
      const end = start + decay / Math.sqrt(ratio)
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(level * amount, start + 0.008)
      gain.gain.exponentialRampToValueAtTime(0.0001, end)
      oscillator.connect(gain)
      oscillator.start(start)
      oscillator.stop(end + 0.05)
      route(gain, 0.55, 0.9)
    }
  }

  // The audio logo: a rising A-major arpeggio over a warm low A.
  function chime(start) {
    bell(659.25, start, 0.16, 2.2) // E5
    bell(880, start + 0.11, 0.14, 2.4) // A5
    bell(1108.73, start + 0.22, 0.12, 2.6) // C#6
    bell(1318.51, start + 0.36, 0.1, 3.2) // E6
    bell(220, start + 0.22, 0.12, 2.8) // A3
  }

  // A low swell and a falling breath as the intro dissolves into the app.
  function outro(start) {
    const filter = context.createBiquadFilter()
    filter.type = 'lowpass'
    filter.frequency.setValueAtTime(4000, start)
    filter.frequency.exponentialRampToValueAtTime(300, start + 1.1)
    const level = context.createGain()
    level.gain.setValueAtTime(0.0001, start)
    level.gain.exponentialRampToValueAtTime(0.12, start + 0.2)
    level.gain.exponentialRampToValueAtTime(0.0001, start + 1.2)
    noiseSource(start, start + 1.3).connect(filter).connect(level)
    route(level, 0.6, 0.6)

    const oscillator = context.createOscillator()
    oscillator.frequency.value = 110
    const tone = context.createGain()
    tone.gain.setValueAtTime(0.0001, start)
    tone.gain.exponentialRampToValueAtTime(0.18, start + 0.15)
    tone.gain.exponentialRampToValueAtTime(0.0001, start + 1.2)
    oscillator.connect(tone)
    oscillator.start(start)
    oscillator.stop(start + 1.3)
    route(tone, 0.8, 0.4)

    bell(880, start + 0.05, 0.05, 1.6)
  }

  // Schedules every cue still ahead of the intro's current time, so sound turned on late joins in step.
  function schedule() {
    const now = context.currentTime + 0.03
    const origin = now - getElapsed() / 1000
    const at = (ms) => origin + ms / 1000
    const ahead = (ms) => at(ms) >= now

    if (full) {
      if (ahead(0)) ambience(at(0), at(timeline.logoLock), at(timeline.exitStart) + 0.6)
      if (ahead(timeline.assembleStart + 400)) whoosh(at(timeline.assembleStart + 400), at(timeline.logoLock))
      if (ahead(timeline.logoLock)) impact(at(timeline.logoLock))
      if (ahead(timeline.nameStart - 150)) chime(at(timeline.nameStart - 150))
    } else if (ahead(300)) {
      chime(at(300))
    }
  }

  return {
    // Starts the sound if the browser lets it. Resolves to whether sound is playing; call it again from a
    // click to start it after autoplay was blocked.
    async start() {
      if (closed) return false
      if (context.state !== 'running') await Promise.race([context.resume().catch(() => {}), wait(RESUME_TIMEOUT_MS)])
      if (closed || context.state !== 'running') return false
      if (!started) {
        started = true
        schedule()
      }
      return true
    },

    playOutro() {
      if (started && !closed) outro(context.currentTime + 0.02)
    },

    // Fades everything out, then frees the audio context. Safe to call more than once.
    stop(fadeSeconds = 0.25) {
      if (closed) return
      closed = true
      const now = context.currentTime
      master.gain.cancelScheduledValues(now)
      master.gain.setValueAtTime(master.gain.value, now)
      master.gain.linearRampToValueAtTime(0, now + fadeSeconds)
      setTimeout(() => context.close().catch(() => {}), fadeSeconds * 1000 + 100)
    },
  }
}
