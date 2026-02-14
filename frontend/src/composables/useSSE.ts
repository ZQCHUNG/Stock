/**
 * SSE (Server-Sent Events) composable for streaming progress from backend.
 * Uses fetch + ReadableStream to handle POST-based SSE endpoints.
 */

export interface SSEProgress {
  current: number
  total: number
  message: string
}

export interface SSECallbacks<T> {
  onProgress?: (progress: SSEProgress) => void
  onDone?: (result: T) => void
  onError?: (message: string) => void
}

export async function fetchSSE<T>(
  url: string,
  body: any,
  callbacks: SSECallbacks<T>,
): Promise<T | null> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const msg = `HTTP ${response.status}`
    callbacks.onError?.(msg)
    return null
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult: T | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Parse SSE events (separated by double newline)
    const parts = buffer.split('\n\n')
    buffer = parts.pop()! // Keep incomplete chunk

    for (const part of parts) {
      const trimmed = part.trim()
      if (!trimmed.startsWith('data: ')) continue

      try {
        const data = JSON.parse(trimmed.slice(6))
        if (data.type === 'progress') {
          callbacks.onProgress?.({
            current: data.current,
            total: data.total,
            message: data.message || '',
          })
        } else if (data.type === 'done') {
          finalResult = data.result as T
          callbacks.onDone?.(finalResult)
        } else if (data.type === 'error') {
          callbacks.onError?.(data.message)
        }
      } catch {
        // ignore parse errors
      }
    }
  }

  return finalResult
}
