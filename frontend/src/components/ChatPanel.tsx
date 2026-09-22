import { useEffect, useRef, useState } from 'react'
import { SUGS } from '../constants'
import type { ChatMessage } from '../types'

type Props = {
  messages: ChatMessage[]
  sending: boolean
  onSend: (text: string) => void
}

export function ChatPanel({ messages, sending, onSend }: Props) {
  const [input, setInput] = useState('')
  const bodyRef = useRef<HTMLDivElement>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const submit = () => {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    if (areaRef.current) areaRef.current.style.height = '40px'
    onSend(text)
  }

  return (
    <div className="chat-center">
      <div className="chat-body" ref={bodyRef}>
        {!messages.length ? (
          <div className="welcome">你好！我是二手交易平台智能客服，有什么可以帮你的？</div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`msg ${m.role}${m.typing ? ' typing' : ''}`}>
              {m.content}
              {m.meta ? <div className="meta">{m.meta}</div> : null}
            </div>
          ))
        )}
      </div>

      <div className="chat-sugs">
        {SUGS.map((s) => (
          <span
            key={s.label}
            className="sug"
            onClick={() => {
              setInput(s.text)
              onSend(s.text)
            }}
          >
            {s.label}
          </span>
        ))}
      </div>

      <div className="chat-input-bar">
        <textarea
          ref={areaRef}
          value={input}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
          rows={1}
          onChange={(e) => {
            setInput(e.target.value)
            e.target.style.height = '40px'
            e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button className="btn" type="button" disabled={sending} onClick={submit}>
          发送
        </button>
      </div>
    </div>
  )
}
