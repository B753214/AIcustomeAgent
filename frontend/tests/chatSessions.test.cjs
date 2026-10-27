const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')

function load(relative) {
  const filename = path.resolve(__dirname, relative)
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const loaded = new Module(filename, module)
  loaded._compile(compiled, filename)
  return loaded.exports
}

const { ChatSessions } = load('../src/api/chatSessions.ts')
const { consumeChatStream } = load('../src/api/chatStream.ts')
const emptyPipe = () => ({ generate: { status: 'wait', ms: null, desc: '' } })
const tick = () => new Promise((resolve) => setImmediate(resolve))

test('A continues streaming while viewing B, switching back restores latest output', async () => {
  const store = new ChatSessions(emptyPipe)
  const a = store.get('A')
  const request = store.begin(a)
  store.update(a, (view) => ({ ...view, sending: true,
    messages: [{ id: 'answer-A', role: 'ai', content: '', typing: true }],
  }))
  let wire
  const body = new ReadableStream({ start(controller) { wire = controller } })
  const send = (event) => wire.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`))
  const consume = consumeChatStream(body, (event) => {
    if (!store.isActive(a, request)) return
    if (event.type === 'model.token') store.update(a, (view) => ({ ...view,
      messages: view.messages.map((message) => ({ ...message, content: message.content + event.content })),
    }))
    if (event.type === 'run.completed') {
      a.request = undefined
      store.update(a, (view) => ({ ...view, sending: false }))
    }
  }, request.controller.signal, () => {})

  send({ type: 'model.token', content: '第一段' })
  await tick()
  const b = store.get('B') // selecting B does not invalidate A
  assert.equal(b.view.sending, false)
  send({ type: 'model.token', content: '第二段' })
  await tick()
  assert.equal(request.controller.signal.aborted, false)
  assert.equal(store.get('A').view.messages[0].content, '第一段第二段')
  assert.deepEqual(store.get('B').view.messages, [])
  assert.equal(store.get('A').view.sending, true)
  assert.deepEqual(store.localSessionIds(), ['A'])
  send({ type: 'run.completed', output: '第一段第二段' })
  await consume
  assert.equal(store.get('A').view.sending, false)
  assert.equal(store.get('A').loaded, true) // do not replace with older DB history
})

test('different sessions can run concurrently; the same session cannot send twice', () => {
  const store = new ChatSessions(emptyPipe)
  const a = store.get('A')
  const b = store.get('B')
  const first = store.begin(a)
  assert.ok(first)
  assert.equal(store.begin(a), null)
  const second = store.begin(b)
  assert.ok(second)
  first.reason = 'stop'
  first.controller.abort()
  assert.equal(second.controller.signal.aborted, false)
})

test('clearing A aborts only A, and late A callbacks cannot overwrite its replacement', () => {
  const store = new ChatSessions(emptyPipe)
  const oldA = store.get('A')
  const aRequest = store.begin(oldA)
  const b = store.get('B')
  const bRequest = store.begin(b)
  store.clear('A')
  assert.equal(aRequest.controller.signal.aborted, true)
  assert.equal(bRequest.controller.signal.aborted, false)
  assert.equal(store.isActive(oldA, aRequest), false)
  store.update(oldA, (view) => ({ ...view, pipeLabel: 'stale' }))
  assert.notEqual(store.get('A').view.pipeLabel, 'stale')
})

test('sending invalidates pending history; background history stays bound to its session', () => {
  const store = new ChatSessions(emptyPipe)
  const a = store.get('A')
  const history = new AbortController()
  a.history = history
  store.get('B')
  assert.equal(history.signal.aborted, false)
  store.begin(a)
  assert.equal(history.signal.aborted, true)
  assert.equal(a.history, undefined)
  assert.equal(a.loaded, true)
})

test('identity change/unmount aborts all requests and invalidates cached state', () => {
  const store = new ChatSessions(emptyPipe)
  const a = store.get('A')
  const b = store.get('B')
  const requestA = store.begin(a)
  const requestB = store.begin(b)
  const c = store.get('C')
  c.history = new AbortController()
  store.dispose()
  assert.equal(requestA.controller.signal.aborted, true)
  assert.equal(requestB.controller.signal.aborted, true)
  assert.equal(c.history.signal.aborted, true)
  assert.equal(store.owns(a), false)
  assert.deepEqual(store.get('A').view.messages, [])
})
