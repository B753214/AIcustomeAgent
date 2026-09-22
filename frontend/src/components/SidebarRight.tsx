import { useRef, useState } from 'react'
import { apiHeaders, formatHttpError } from '../api/client'
import { STAGES } from '../constants'
import type { PipeStageState } from '../types'

type Props = {
  pipeState: Record<string, PipeStageState>
  pipeLabel: string
  sources: string[]
  apiKey: string
  onUploaded?: () => void
}

export function SidebarRight({ pipeState, pipeLabel, sources, apiKey, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploadResult, setUploadResult] = useState<string>('')
  const [uploadOk, setUploadOk] = useState(false)

  const uploadFile = async (file?: File | null) => {
    if (!file) return
    setUploadResult(`上传中: ${file.name}…`)
    setUploadOk(false)
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/api/v1/ingest', {
        method: 'POST',
        headers: apiHeaders({}, apiKey),
        body: form,
      })
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}))
        const msg =
          resp.status === 401
            ? '无效或缺失 API Key，请在左侧「API 鉴权」填写'
            : formatHttpError(j, resp.status)
        throw new Error(msg)
      }
      const d = (await resp.json()) as {
        file_name: string
        chunks: number
        total_chunks: number
      }
      setUploadOk(true)
      setUploadResult(`✅ ${d.file_name} — 新增 ${d.chunks} 块，总计 ${d.total_chunks} 块`)
      onUploaded?.()
    } catch (err) {
      setUploadOk(false)
      setUploadResult(`❌ ${err instanceof Error ? err.message : String(err)}`)
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="sidebar-right">
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-title">
          全链路可视化 <span className="pipe-state">{pipeLabel}</span>
        </div>
        <div>
          {STAGES.map((s) => {
            const st = pipeState[s.key] || { status: 'wait', ms: null, desc: '' }
            return (
              <div key={s.key} className={`pstep ${st.status}`}>
                <div className="icon">{s.icon}</div>
                <div className="body">
                  <div className="title">
                    {s.name} {st.ms != null ? <span className="ms">{st.ms}ms</span> : null}
                  </div>
                  {st.desc ? <div className="desc">{st.desc}</div> : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          来源引用{' '}
          <span className="tag">{sources.length ? `${sources.length} 条` : ''}</span>
        </div>
        <div>
          {!sources.length ? (
            <span className="sources-empty">等待对话…</span>
          ) : (
            sources.map((s) => (
              <span key={s} className="source-tag" title={s}>
                {s}
              </span>
            ))
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">知识库上传</div>
        <div
          className={`upload-zone${dragOver ? ' dragover' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            void uploadFile(e.dataTransfer.files[0])
          }}
        >
          拖拽文件到此处，或点击选择
          <br />
          <span style={{ fontSize: 11 }}>支持 PDF / DOCX / MD / TXT</span>
        </div>
        <input
          ref={inputRef}
          type="file"
          style={{ display: 'none' }}
          accept=".pdf,.docx,.md,.txt,.markdown"
          onChange={(e) => void uploadFile(e.target.files?.[0])}
        />
        <div className="upload-result">
          {uploadResult ? <span className={uploadOk ? 'ok' : 'err'}>{uploadResult}</span> : null}
        </div>
      </div>
    </div>
  )
}
