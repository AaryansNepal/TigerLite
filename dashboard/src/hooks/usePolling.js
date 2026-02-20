import { useState, useEffect, useCallback, useRef } from 'react'

export function usePolling(fetchFn, intervalMs = 3000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [isFirstLoad, setIsFirstLoad] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const mountedRef = useRef(true)

  const refresh = useCallback(async () => {
    setIsRefreshing(true)
    try {
      const result = await fetchFn()
      if (mountedRef.current) {
        setData(result)
        setError(null)
        setIsFirstLoad(false)
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e.message)
      }
    } finally {
      if (mountedRef.current) {
        setIsRefreshing(false)
      }
    }
  }, [fetchFn])

  useEffect(() => {
    mountedRef.current = true
    refresh()
    const id = setInterval(refresh, intervalMs)
    return () => {
      mountedRef.current = false
      clearInterval(id)
    }
  }, [refresh, intervalMs])

  return { data, error, isFirstLoad, isRefreshing, refresh }
}
