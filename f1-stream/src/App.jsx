import { useEffect, useRef, useState } from 'react'
import './App.css'

const STREAM_SRC = '/lando.mp4'
const RECOVERY_MAX_ATTEMPTS = 4
const RECOVERY_BASE_DELAY_MS = 500
const HEALTH_CHECK_INTERVAL_MS = 2000
const DRIFT_THRESHOLD_SECONDS = 0.4
const ONBOARD_SYNC_INTERVAL_MS = 500

const ONBOARD_DELAYS = [6, 12, 18]

function loopDriftSeconds(currentTime, targetTime, duration) {
  const delta = Math.abs(currentTime - targetTime)
  return Math.min(delta, duration - delta)
}

function configureVideo(video) {
  video.muted = true
  video.defaultMuted = true
  video.loop = true
  video.playsInline = true
  video.autoplay = true
  video.preload = 'auto'
}

function attachRecovery(video, { onFatal, onRecovered } = {}) {
  let isUnmounted = false
  let recoveryAttempts = 0
  let healthCheckId
  let retryTimeoutId

  const tryPlay = () =>
    video
      .play()
      .then(() => true)
      .catch(() => false)

  const clearRetryTimeout = () => {
    if (retryTimeoutId === undefined) return
    window.clearTimeout(retryTimeoutId)
    retryTimeoutId = undefined
  }

  const markRecovered = () => {
    if (isUnmounted) return
    clearRetryTimeout()
    recoveryAttempts = 0
    onRecovered?.()
  }

  const scheduleRecovery = () => {
    if (isUnmounted || retryTimeoutId !== undefined) return

    if (recoveryAttempts >= RECOVERY_MAX_ATTEMPTS) {
      onFatal?.()
      return
    }

    recoveryAttempts += 1
    const backoffMs = RECOVERY_BASE_DELAY_MS * 2 ** (recoveryAttempts - 1)
    retryTimeoutId = window.setTimeout(() => {
      retryTimeoutId = undefined
      void recoverPlayback()
    }, backoffMs)
  }

  const recoverPlayback = async () => {
    if (isUnmounted) return

    if (await tryPlay()) {
      markRecovered()
      return
    }

    const resumeTime = Number.isFinite(video.currentTime) ? video.currentTime : 0
    const handleLoadedMetadata = async () => {
      if (isUnmounted) return

      if (resumeTime > 0 && Number.isFinite(video.duration)) {
        const maxSeek = Math.max(video.duration - 0.05, 0)
        video.currentTime = Math.min(resumeTime, maxSeek)
      }

      if (await tryPlay()) {
        markRecovered()
        return
      }

      scheduleRecovery()
    }

    video.addEventListener('loadedmetadata', handleLoadedMetadata, { once: true })
    video.load()
  }

  const handleCanPlay = () => {
    void tryPlay().then((playing) => {
      if (playing) {
        markRecovered()
        return
      }

      scheduleRecovery()
    })
  }

  const handleEnded = () => {
    video.currentTime = 0
    void tryPlay().then((playing) => {
      if (!playing) scheduleRecovery()
    })
  }

  const handleError = () => scheduleRecovery()
  const handleStalled = () => scheduleRecovery()

  configureVideo(video)

  video.addEventListener('canplay', handleCanPlay)
  video.addEventListener('ended', handleEnded)
  video.addEventListener('error', handleError)
  video.addEventListener('stalled', handleStalled)

  void tryPlay().then((playing) => {
    if (playing) {
      markRecovered()
      return
    }

    scheduleRecovery()
  })

  healthCheckId = window.setInterval(() => {
    if (!video.paused || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return

    void tryPlay().then((playing) => {
      if (playing) {
        markRecovered()
        return
      }

      scheduleRecovery()
    })
  }, HEALTH_CHECK_INTERVAL_MS)

  return () => {
    isUnmounted = true
    clearRetryTimeout()
    window.clearInterval(healthCheckId)
    video.removeEventListener('canplay', handleCanPlay)
    video.removeEventListener('ended', handleEnded)
    video.removeEventListener('error', handleError)
    video.removeEventListener('stalled', handleStalled)
  }
}

export default function App() {
  const mainRef = useRef(null)
  const onboardOneRef = useRef(null)
  const onboardTwoRef = useRef(null)
  const onboardThreeRef = useRef(null)
  const [playbackError, setPlaybackError] = useState(false)

  useEffect(() => {
    const videos = [mainRef.current, onboardOneRef.current, onboardTwoRef.current, onboardThreeRef.current]

    if (videos.some((video) => !video)) return undefined

    const cleanups = videos.map((video, index) =>
      attachRecovery(video, {
        onFatal: index === 0 ? () => setPlaybackError(true) : undefined,
        onRecovered: index === 0 ? () => setPlaybackError(false) : undefined,
      }),
    )

    return () => {
      cleanups.forEach((cleanup) => cleanup())
    }
  }, [])

  useEffect(() => {
    const main = mainRef.current
    const onboardVideos = [onboardOneRef.current, onboardTwoRef.current, onboardThreeRef.current]

    if (!main || onboardVideos.some((video) => !video)) return undefined

    const syncOnboards = () => {
      if (!Number.isFinite(main.duration) || main.duration <= 0 || !Number.isFinite(main.currentTime)) return

      const duration = main.duration
      const mainTime = main.currentTime

      onboardVideos.forEach((video, index) => {
        if (!video) return

        if (
          video.readyState < HTMLMediaElement.HAVE_METADATA ||
          !Number.isFinite(video.duration) ||
          video.duration <= 0 ||
          !Number.isFinite(video.currentTime)
        ) {
          return
        }

        const delay = ONBOARD_DELAYS[index]
        const targetTime = ((mainTime - delay) % duration + duration) % duration

        if (loopDriftSeconds(video.currentTime, targetTime, duration) > DRIFT_THRESHOLD_SECONDS) {
          video.currentTime = targetTime
        }
      })
    }

    const syncId = window.setInterval(syncOnboards, ONBOARD_SYNC_INTERVAL_MS)
    return () => window.clearInterval(syncId)
  }, [])

  return (
    <main className="stream-shell">
      <div className="tv-bezel">
        <div className="screen-surface">
          <section className="main-feed">
            <video ref={mainRef} className="feed-video" src={STREAM_SRC} autoPlay muted loop playsInline preload="auto" />
            <div className="video-vignette" />
          </section>

          <aside className="side-stack">
            <section className="stack-panel">
              <video
                ref={onboardOneRef}
                className="feed-video feed-video--onboard"
                src={STREAM_SRC}
                autoPlay
                muted
                loop
                playsInline
                preload="auto"
              />
            </section>

            <section className="stack-panel">
              <video
                ref={onboardTwoRef}
                className="feed-video feed-video--onboard"
                src={STREAM_SRC}
                autoPlay
                muted
                loop
                playsInline
                preload="auto"
              />
            </section>

            <section className="stack-panel stack-panel--wide">
              <video
                ref={onboardThreeRef}
                className="feed-video feed-video--aux"
                src={STREAM_SRC}
                autoPlay
                muted
                loop
                playsInline
                preload="auto"
              />
            </section>
          </aside>
        </div>
      </div>

      {playbackError ? (
        <p className="stream-error">
          Stream error: unable to load <code>{STREAM_SRC}</code>
        </p>
      ) : null}
    </main>
  )
}
