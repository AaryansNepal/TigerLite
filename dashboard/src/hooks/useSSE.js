import { useState, useEffect, useRef } from 'react'

export function useSSE(url, maxEvents = 100) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const sourceRef = useRef(null)

  useEffect(() => {
    const es = new EventSource(url)
    sourceRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        setEvents(prev => {
          const next = [parsed, ...prev]
          return next.slice(0, maxEvents)
        })
      } catch {
        // ignore non-JSON messages
      }
    }

    return () => {
      es.close()
      setConnected(false)
    }
  }, [url, maxEvents])

  return { events, connected }
}
