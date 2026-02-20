import { useState, useEffect, useRef, useCallback } from 'react'

export function useSSE(url, maxEvents = 200) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [paused, setPaused] = useState(false)
  const sourceRef = useRef(null)
  const bufferRef = useRef([])
  const rafRef = useRef(null)
  const pausedRef = useRef(false)

  const flushBuffer = useCallback(() => {
    rafRef.current = null
    if (bufferRef.current.length === 0) return
    const batch = bufferRef.current
    bufferRef.current = []
    setEvents(prev => {
      const next = [...batch, ...prev]
      return next.slice(0, maxEvents)
    })
  }, [maxEvents])

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  useEffect(() => {
    const es = new EventSource(url)
    sourceRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.onmessage = (event) => {
      if (pausedRef.current) return
      try {
        const parsed = JSON.parse(event.data)
        bufferRef.current.push(parsed)
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(flushBuffer)
        }
      } catch {
        // ignore non-JSON messages
      }
    }

    return () => {
      es.close()
      setConnected(false)
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [url, flushBuffer])

  const togglePause = useCallback(() => {
    setPaused(p => !p)
  }, [])

  const clearEvents = useCallback(() => {
    setEvents([])
    bufferRef.current = []
  }, [])

  return { events, connected, paused, togglePause, clearEvents }
}
