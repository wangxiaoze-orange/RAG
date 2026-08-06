// SSE 客户端：fetch 流式解析（Named Events，可带 Authorization header）
// 用法：
//   chatStream(payload, {
//     onEvent: (event, data) => { ... },   // session/stage/tool_call/token/cache_hit/memory/intent/review/error/done
//   }, { signal })

export function chatStream(payload, handlers = {}, { signal } = {}) {
  return new Promise((resolve, reject) => {
    const ctrl = new AbortController()
    const onAbort = () => ctrl.abort()
    if (signal) {
      if (signal.aborted) ctrl.abort()
      else signal.addEventListener('abort', onAbort, { once: true })
    }

    fetch('/api/v2/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('rag_token') || ''}`,
      },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    })
      .then(async (resp) => {
        if (!resp.ok) {
          const text = await resp.text()
          throw new Error(`HTTP ${resp.status}: ${text.slice(0, 300)}`)
        }
        const reader = resp.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buf = ''

        const parseBlock = () => {
          let idx
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, idx)
            buf = buf.slice(idx + 2)
            const evt = block.match(/^event: (.+)$/m)?.[1]
            const data = block.match(/^data: (.+)$/m)?.[1]
            if (!evt || !data) continue
            let parsed
            try {
              parsed = JSON.parse(data)
            } catch {
              continue
            }
            handlers.onEvent?.(evt, parsed)
          }
        }

        const pump = async () => {
          try {
            for (;;) {
              const { done, value } = await reader.read()
              if (done) break
              buf += decoder.decode(value, { stream: true })
              parseBlock()
            }
            resolve()
          } catch (e) {
            if (e.name === 'AbortError') {
              const err = new Error('请求已取消')
              err.name = 'AbortError'
              reject(err)
            } else {
              reject(e)
            }
          }
        }
        pump()
      })
      .catch((e) => {
        if (e.name === 'AbortError') {
          const err = new Error('请求已取消')
          err.name = 'AbortError'
          reject(err)
        } else {
          reject(e)
        }
      })
  })
}
