import { useEffect, useRef, useState } from 'react'
import './App.css'

const STREAM_SRC = '/lando.mp4'

export default function App() {
  const videoRef = useRef(null)
  const [playbackError, setPlaybackError] = useState(false)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined

    const MAX_RECOVERY_ATTEMPTS = 4
    const RECOVERY_BASE_MS = 500

    let isUnmounted = false
    let recoveryAttempts = 0
    let healthCheckId
    let retryTimeoutId

    const tryPlay = () =>
      video
        .play()
        .then(() => true)
        .catch(() => {
          // Autoplay can be blocked in some browser policies despite muted=true.
          return false
        })

    const clearRetryTimeout = () => {
      if (retryTimeoutId === undefined) return
      window.clearTimeout(retryTimeoutId)
      retryTimeoutId = undefined
    }

    const markRecovered = () => {
      if (isUnmounted) return
      clearRetryTimeout()
      recoveryAttempts = 0
      setPlaybackError(false)
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

    const scheduleRecovery = () => {
      if (isUnmounted || retryTimeoutId !== undefined) return

      if (recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
        setPlaybackError(true)
        return
      }

      recoveryAttempts += 1
      const backoffMs = RECOVERY_BASE_MS * 2 ** (recoveryAttempts - 1)
      retryTimeoutId = window.setTimeout(() => {
        retryTimeoutId = undefined
        void recoverPlayback()
      }, backoffMs)
    }

    const handleCanPlay = () => {
      recoveryAttempts = 0
      void tryPlay().then((playing) => {
        if (playing) markRecovered()
      })
    }

    const handleEnded = () => {
      // Defensive replay guard for browsers that still dispatch `ended`.
      video.currentTime = 0
      void tryPlay().then((playing) => {
        if (!playing) scheduleRecovery()
      })
    }

    const handleError = () => scheduleRecovery()
    const handleStalled = () => scheduleRecovery()

    video.muted = true
    video.defaultMuted = true
    video.loop = true
    video.playsInline = true
    video.autoplay = true
    video.preload = 'auto'

    video.addEventListener('canplay', handleCanPlay)
    video.addEventListener('ended', handleEnded)
    video.addEventListener('error', handleError)
    video.addEventListener('stalled', handleStalled)

    void tryPlay()

    healthCheckId = window.setInterval(() => {
      if (!video.paused || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return
      void tryPlay().then((playing) => {
        if (!playing) scheduleRecovery()
      })
    }, 2000)

    return () => {
      isUnmounted = true
      clearRetryTimeout()
      window.clearInterval(healthCheckId)
      video.removeEventListener('canplay', handleCanPlay)
      video.removeEventListener('ended', handleEnded)
      video.removeEventListener('error', handleError)
      video.removeEventListener('stalled', handleStalled)
    }
  }, [])

  return (
    <main className="stream-shell">
      <video
        ref={videoRef}
        className="stream-video"
        src={STREAM_SRC}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
      />
      {playbackError ? (
        <p className="stream-error">
          Stream error: unable to load <code>{STREAM_SRC}</code>
        </p>
      ) : null}
    </main>
  )
}
