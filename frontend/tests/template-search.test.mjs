import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { test } from 'node:test'

const source = readFileSync(new URL('../src/lib/templates.ts', import.meta.url), 'utf8')
const moduleUrl = `data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`
const { filterGroups } = await import(moduleUrl)
const item = { label: 'dir', name: 'dir', type: 'directory', category: 'General', attrs: {}, ports: [] }
const groups = [{ category: 'General', items: [item] }]

test('a displayed type remains searchable when its template has a different name', () => {
  assert.deepEqual(filterGroups(groups, 'directory'), groups)
  assert.deepEqual(filterGroups(groups, '  DIRECTORY  '), groups)
})

test('type search preserves catalog filtering and existing label/category search', () => {
  assert.deepEqual(filterGroups([], 'directory'), [])
  assert.deepEqual(filterGroups(groups, 'module'), [])
  assert.deepEqual(filterGroups(groups, 'dir'), groups)
  assert.deepEqual(filterGroups(groups, 'general'), groups)
  assert.equal(filterGroups(groups, '  '), groups)
  assert.deepEqual(groups, [{ category: 'General', items: [item] }])
})
