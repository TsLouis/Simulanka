import assert from 'node:assert/strict'
import { createServer as createHttpServer } from 'node:http'
import { test } from 'node:test'
import { createServer, loadConfigFromFile } from 'vite'

test('development proxy forwards Port update/delete to the configured API', { timeout: 20000 }, async () => {
  const received = []
  const upstream = createHttpServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    received.push({ method: req.method, url: req.url, body: Buffer.concat(chunks).toString() })
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ from: 'api' }))
  })
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve))
  const previous = process.env.SIMULANKA_API_TARGET
  let vite
  try {
    process.env.SIMULANKA_API_TARGET = `http://127.0.0.1:${upstream.address().port}`
    const loaded = await loadConfigFromFile({ command: 'serve', mode: 'test' })
    assert.ok(loaded, 'load the actual checked-in Vite configuration')
    vite = await createServer({
      configFile: false,
      server: { ...loaded.config.server, host: '127.0.0.1', port: 0, hmr: false },
    })
    await vite.listen()
    const base = `http://127.0.0.1:${vite.httpServer.address().port}`
    const body = JSON.stringify({ name: 'features' })
    const update = await fetch(`${base}/port/port-smoke/update`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body,
    })
    assert.equal(update.status, 200)
    assert.deepEqual(await update.json(), { from: 'api' })
    const deletion = await fetch(`${base}/port/port-smoke`, { method: 'DELETE' })
    assert.equal(deletion.status, 200)
    assert.deepEqual(await deletion.json(), { from: 'api' })
    assert.deepEqual(received, [
      { method: 'POST', url: '/port/port-smoke/update', body },
      { method: 'DELETE', url: '/port/port-smoke', body: '' },
    ])
  } finally {
    if (previous === undefined) delete process.env.SIMULANKA_API_TARGET
    else process.env.SIMULANKA_API_TARGET = previous
    await vite?.close()
    await new Promise((resolve, reject) => upstream.close(error => error ? reject(error) : resolve()))
  }
})
