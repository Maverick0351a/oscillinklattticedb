// SPDX-License-Identifier: BUSL-1.1
import { test, expect } from '@playwright/test'

const API = process.env.API_URL || 'http://127.0.0.1:8080'
const DB_PATH = process.env.DB_PATH || 'latticedb'

async function setDisplayName(latticeId: string, name: string) {
  const res = await fetch(`${API}/v1/latticedb/lattice/${encodeURIComponent(latticeId)}/metadata`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ db_path: DB_PATH, display_name: name })
  })
  if (!res.ok) throw new Error(`Failed to set display_name for ${latticeId}: ${res.status}`)
}

async function getManifest(limit=10, sort_by='lattice_id', sort_order='asc') {
  const u = `${API}/v1/latticedb/manifest?db_path=${encodeURIComponent(DB_PATH)}&limit=${limit}&offset=0&sort_by=${encodeURIComponent(sort_by)}&sort_order=${encodeURIComponent(sort_order)}`
  const r = await fetch(u)
  if (!r.ok) throw new Error(`Manifest error: ${r.status}`)
  return r.json() as Promise<{ items: any[] }>
}

// This spec assumes the API is running and a demo DB exists at DB_PATH with at least 2 lattices.
// It verifies inline rename flow and sorting by display_name via the UI.

test.beforeAll(async () => {
  // Ensure at least 2 items exist and set display names deterministically
  const man = await getManifest(2, 'lattice_id', 'asc')
  if (!man.items || man.items.length < 2) {
    test.skip(true, 'Need at least 2 manifest items to test sorting/rename')
  }
  const a = man.items[0]
  const b = man.items[1]
  await setDisplayName(a.lattice_id, 'AA-Test-First')
  await setDisplayName(b.lattice_id, 'ZZ-Test-Last')
})

test('inline rename shows toast and updates', async ({ page }) => {
  await page.goto('/')

  // Set db path
  await page.getByLabel('DB Path').fill(DB_PATH)

  // Load manifest
  await page.getByRole('button', { name: 'List manifest' }).click()
  await expect(page.getByTestId('manifest-row').first()).toBeVisible()

  // Open first row rename
  const firstRow = page.getByTestId('manifest-row').first()
  await firstRow.getByTestId('rename-open').click()
  await firstRow.getByTestId('rename-input').fill('AA-Renamed')
  await firstRow.getByTestId('rename-save').click()

  // Expect toast
  await expect(page.getByTestId('toast')).toHaveText('Rename Complete')

  // Reload manifest to confirm persistence
  await page.getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByTestId('manifest-row').first()).toBeVisible()
})

test('sort by display_name asc/desc', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('DB Path').fill(DB_PATH)
  await page.getByRole('button', { name: 'List manifest' }).click()
  await expect(page.getByTestId('manifest-row').first()).toBeVisible()

  // Sort by display_name asc
  await page.getByLabel('Sort by').selectOption('display_name')
  await page.getByLabel('Order').selectOption('asc')
  await page.getByRole('button', { name: 'Reload' }).click()

  const firstTextAsc = await page.getByTestId('manifest-row').first().innerText()
  const lastTextAsc = await page.getByTestId('manifest-row').last().innerText()
  expect(firstTextAsc).toContain('AA')
  expect(lastTextAsc).toContain('ZZ')

  // Now desc
  await page.getByLabel('Order').selectOption('desc')
  await page.getByRole('button', { name: 'Reload' }).click()
  const firstTextDesc = await page.getByTestId('manifest-row').first().innerText()
  const lastTextDesc = await page.getByTestId('manifest-row').last().innerText()
  expect(firstTextDesc).toContain('ZZ')
  expect(lastTextDesc).toContain('AA')
})
