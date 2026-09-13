import assert from 'node:assert/strict'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const source = await readFile(resolve(here, '../src/lib/agent-projection.ts'), 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText
const module = { exports: {} }
vm.runInNewContext(transpiled, {
  module,
  exports: module.exports,
  require: () => ({}),
})
const { conversationProjectionFromEvents } = module.exports

test('uses only the latest user turn explicit ContextBundle refs', () => {
  const projection = conversationProjectionFromEvents([
    {
      type: 'user_msg',
      details: { context_bundles: [{ refs: [{ kind: 'node', ref_id: 'old' }] }] },
    },
    { type: 'agent_text', text: 'old answer' },
    {
      type: 'user_msg',
      details: {
        context_bundles: [{
          refs: [
            { kind: 'node', ref_id: 'n1' },
            { kind: 'edge', ref_id: 'e1' },
            { kind: 'node', ref_id: 'n1' },
          ],
        }],
      },
    },
    { type: 'status', status: 'running' },
    { type: 'agent_text', text: 'new answer' },
  ])

  assert.deepEqual(projection, {
    refs: [
      { kind: 'node', ref_id: 'n1' },
      { kind: 'edge', ref_id: 'e1' },
    ],
    text: 'new answer',
  })
})

test('does not infer projection targets from prose or selection-like details', () => {
  const projection = conversationProjectionFromEvents([
    { type: 'user_msg', text: 'look at node n1' },
    { type: 'agent_text', text: 'I think n1 is suspicious' },
  ])
  assert.deepEqual(projection, { refs: [], text: null })
})

test('ignores malformed context refs', () => {
  const projection = conversationProjectionFromEvents([
    {
      type: 'user_msg',
      details: {
        context_bundles: [{
          refs: [
            { kind: 'node', ref_id: '' },
            { kind: 'file', ref_id: 'x' },
            { kind: 'port', ref_id: 'p1' },
          ],
        }],
      },
    },
  ])
  assert.deepEqual(projection, {
    refs: [{ kind: 'port', ref_id: 'p1' }],
    text: null,
  })
})
