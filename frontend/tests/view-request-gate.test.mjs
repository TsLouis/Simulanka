import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/lib/view-request-gate.ts', import.meta.url), 'utf8')
const moduleUrl = `data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`
const { ViewRequestGate } = await import(moduleUrl)

test('only the newest request for the active view may commit', () => {
  const gate = new ViewRequestGate()
  const first = gate.begin('a')
  const next = gate.begin('b')
  assert.equal(gate.accepts(first, 'b'), false)
  assert.equal(gate.accepts(next, 'b'), true)
})
test('same-root reloads still supersede earlier responses', () => {
  const gate = new ViewRequestGate()
  const first = gate.begin(null)
  const next = gate.begin(null)
  assert.equal(gate.accepts(first, null), false)
  assert.equal(gate.accepts(next, null), true)
})
test('navigation invalidates a response before the next load begins', () => {
  const gate = new ViewRequestGate()
  const pending = gate.begin('a')
  assert.equal(gate.accepts(pending, 'b'), false)
})
test('returning to a previous root cannot revive an old response', () => {
  const gate = new ViewRequestGate()
  const firstA = gate.begin('a')
  gate.begin('b')
  const latestA = gate.begin('a')
  assert.equal(gate.accepts(firstA, 'a'), false)
  assert.equal(gate.accepts(latestA, 'a'), true)
})
test('disposal permanently rejects pending and future work', () => {
  const gate = new ViewRequestGate()
  const pending = gate.begin(null)
  gate.dispose()
  gate.dispose()
  assert.equal(gate.disposed, true)
  assert.equal(gate.accepts(pending, null), false)
  assert.equal(gate.accepts(gate.begin(null), null), false)
})
