const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')

// Run the production TypeScript with the existing compiler; no test dependencies.
const filename = path.resolve(__dirname, '../src/api/chatStream.ts')
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const loaded = new Module(filename, module)
loaded._compile(compiled, filename)
const { consumeChatStream, parseChatEvent } = loaded.exports
const encoder = new TextEncoder()
const frame = (event) => `data: ${JSON.stringify(event)}\n\n`
const completed = { type: 'run.completed', output: '你好' }

function stream(text, bytewise = false) {
  const bytes = encoder.encode(text)
  return new ReadableStream({
    start(controller) {
      if (bytewise) for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      else controller.enqueue(bytes)
      controller.close()
    },
  })
}

test('decodes split UTF-8 and multiple standard events', async () => {
  const events = []
  await consumeChatStream(stream(
    frame({ type: 'model.token', content: '你' }) + frame(completed), true,
  ), (event) => events.push(event), new AbortController().signal, () => {})
  assert.deepEqual(events, [{ type: 'model.token', content: '你' }, completed])
})

test('waits for the blank line and concatenates token content without protocol newlines', async () => {
  const events = []
  let wire
  const body = new ReadableStream({ start(controller) { wire = controller } })
  const send = (text) => wire.enqueue(encoder.encode(text))
  const consuming = consumeChatStream(body, (event) => events.push(event),
    new AbortController().signal, () => {})
  send('data: {"type":"model.token","content":"混合检索结合了"}\n')
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(events.length, 0)
  send('\ndata: {"type":"model.token","content":"向量检索和关键词检索，"}\n\n')
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(events.length, 2)
  assert.equal(events.map((event) => event.content).join(''), '混合检索结合了向量检索和关键词检索，')
  send(frame(completed))
  await consuming
})

test('supports CRLF split across chunks, comments, id and multiline data', async () => {
  const events = []
  const text = ': heartbeat\r\nid: 1\r\ndata: {"type":"run.completed",\r\ndata: "output":"ok"}\r\n\r\n'
  await consumeChatStream(stream(text, true), (event) => events.push(event),
    new AbortController().signal, () => {})
  assert.deepEqual(events, [{ type: 'run.completed', output: 'ok' }])
})

test('premature EOF preserves delivered events but rejects incomplete run', async () => {
  const events = []
  await assert.rejects(consumeChatStream(
    stream(frame({ type: 'model.token', content: 'partial' })),
    (event) => events.push(event), new AbortController().signal, () => {},
  ), /未收到任务完成通知/)
  assert.equal(events[0].content, 'partial')
})

test('truncated final event is not mistaken for success', async () => {
  await assert.rejects(consumeChatStream(
    stream('data: {"type":"run.completed"}\n'), () => {},
    new AbortController().signal, () => {},
  ), /未收到任务完成通知/)
})

test('DONE transport marker alone does not count as run completion', async () => {
  await assert.rejects(consumeChatStream(stream('data: [DONE]\n\n'), () => {},
    new AbortController().signal, () => {}), /未收到任务完成通知/)
})

test('malformed JSON and invalid event shape report protocol errors', async () => {
  assert.throws(() => parseChatEvent('[]'), /type/)
  await assert.rejects(consumeChatStream(stream('data: {bad}\n\n'), () => {},
    new AbortController().signal, () => {}), /格式错误/)
})

test('run.failed is a terminal event; callback errors are not swallowed', async () => {
  const events = []
  await consumeChatStream(stream(frame({ type: 'run.failed', message: 'failed' })),
    (event) => events.push(event), new AbortController().signal, () => {})
  assert.equal(events[0].type, 'run.failed')
  await assert.rejects(consumeChatStream(stream(frame(completed)), () => {
    throw new Error('render failed')
  }, new AbortController().signal, () => {}), /render failed/)
})

test('completion ends reading even when server leaves connection open', async () => {
  let cancelled = false
  const body = new ReadableStream({
    start(controller) { controller.enqueue(encoder.encode(frame(completed))) },
    cancel() { cancelled = true },
  })
  await consumeChatStream(body, () => {}, new AbortController().signal, () => {})
  assert.equal(cancelled, true)
  assert.equal(body.locked, false)
})

test('abort unblocks an idle read and releases its reader', async () => {
  let cancelled = false
  const body = new ReadableStream({ cancel() { cancelled = true } })
  const controller = new AbortController()
  const result = consumeChatStream(body, () => assert.fail('stale event'), controller.signal, () => {})
  controller.abort()
  await assert.rejects(result, { name: 'AbortError' })
  assert.equal(cancelled, true)
  assert.equal(body.locked, false)
})

test('legacy token/done events remain supported', async () => {
  const events = []
  await consumeChatStream(stream(frame({ type: 'token', content: 'ok' }) + frame({ type: 'done' })),
    (event) => events.push(event), new AbortController().signal, () => {})
  assert.deepEqual(events.map((event) => event.type), ['token', 'done'])
})

test('heartbeat resets activity without producing UI events', async () => {
  const events = []
  let activity = 0
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(': heartbeat\n\n'))
      controller.enqueue(encoder.encode(frame(completed)))
      controller.close()
    },
  })
  await consumeChatStream(body, (event) => events.push(event),
    new AbortController().signal, () => { activity++ })
  assert.equal(activity, 2)
  assert.deepEqual(events, [completed])
})
