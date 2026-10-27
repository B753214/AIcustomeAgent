export type ChatEvent = Record<string, unknown> & { type: string }

export function parseChatEvent(data: string): ChatEvent | null {
  if (data === '[DONE]') return null // transport marker, not proof of run success
  let value: unknown
  try {
    value = JSON.parse(data)
  } catch {
    throw new Error('流式事件格式错误，回答已中断')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || typeof (value as Record<string, unknown>).type !== 'string') {
    throw new Error('流式事件缺少有效的 type 字段')
  }
  return value as ChatEvent
}

export function isTerminalEvent(event: ChatEvent) {
  return ['run.completed', 'run.failed', 'done', 'error'].includes(event.type)
}

export async function consumeChatStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
  onActivity: () => void,
) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const cancel = () => { void reader.cancel().catch(() => {}) }
  signal.addEventListener('abort', cancel, { once: true })
  try {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    while (true) {
      const { done, value } = await reader.read()
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (!done) onActivity()

      // 1. 字节解码后追加到缓冲区；兼容服务器或代理使用 CRLF 换行。
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n/g, '\n') //把 Windows 风格的换行 \r\n 统一成 \n

      // 2. 空行分隔完整事件；最后一段没有结束空行，留给下一批数据。
      const completeEvents = buffer.split('\n\n')
      buffer = completeEvents.pop() || ''

      // 3. 每个完整事件单独解析，随后更新对应会话。
      for (const eventText of completeEvents) {
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
        const dataLines = eventText.split('\n')
          .filter((line) => line === 'data' || line.startsWith('data:'))
          .map((line) => line === 'data' ? '' : line.slice(5).replace(/^ /, ''))
        if (!dataLines.length) continue // 跳过心跳注释等不含数据的事件。

        // 当前后端每个事件只有一行 data；join 也兼容同一事件的多行 data。
        const event = parseChatEvent(dataLines.join('\n'))
        if (!event) continue
        onEvent(event)
        if (isTerminalEvent(event)) return // 收到完成/失败事件，结束读取。
      }

      if (done) throw new Error('连接提前结束，未收到任务完成通知')
    }
  } finally {
    signal.removeEventListener('abort', cancel)
    // Do not wait indefinitely for a broken transport during cleanup.
    void reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
