import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import App from './App'

// Mock fetch globally
const g: any = globalThis as any

beforeEach(() => {
  g.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    // Default stubs for admin endpoints to avoid interfering messages
    if (String(url).includes('/v1/db/scan')) {
      return new Response(JSON.stringify({ scanned: true }), { status: 200 })
    }
    if (String(url).includes('/readyz')) {
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }
    if (String(url).includes('/v1/latticedb/manifest')) {
      return new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 })
    }
    if (String(url).includes('/v1/db/receipt') && !String(url).endsWith('/v1/db/receipt')) {
      // Query form from admin panel handled above; leave main receipt to specific tests
      return new Response(JSON.stringify({}), { status: 200 })
    }
    if (String(url).includes('/v1/license/status')) {
      return new Response(JSON.stringify({ mode: 'dev', notice: 'for testing' }), { status: 200 })
    }
    if (String(url).includes('/v1/latticedb/route')) {
      return new Response(
        JSON.stringify({
          candidates: [
            { lattice_id: 'G-000001', score: 0.91 },
            { lattice_id: 'G-000002', score: 0.74 },
          ],
        }),
        { status: 200 }
      )
    }
    if (String(url).includes('/v1/latticedb/compose')) {
      return new Response(
        JSON.stringify({
          context_pack: {
            receipts: {
              composite: { db_root: 'abc123' },
            },
          },
        }),
        { status: 200 }
      )
    }
    if (String(url).includes('/v1/db/receipt')) {
      return new Response(JSON.stringify({ db_root: 'abc123' }), { status: 200 })
    }
    return new Response('not found', { status: 404 })
  })
})

describe('App', () => {
  it('renders and runs a happy path flow', async () => {
    render(<App />)

    // License footer info loads
    await screen.findByText(/License: dev — for testing/i)

    // Run pipeline
      const runBtns = screen.getAllByRole('button', { name: /Run/i })
        const runBtn = screen.getByRole('button', { name: /^Run$/ })
        fireEvent.click(runBtn)

    // Candidates show up
    await screen.findByText(/Candidate lattices/i)
    await screen.findByText(/G-000001/i)

    // Context pack appears
    await screen.findByText(/Context Pack/i)

    // Verify against DB root
    const verifyBtn = screen.getByRole('button', { name: /Verify against DB root/i })
    fireEvent.click(verifyBtn)

    await screen.findByText(/Composite matches DB root/i)
  })

  it('handles missing composite receipt on verify', async () => {
    // Override compose response to have no composite
    ;(g.fetch as any) = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/v1/db/scan')) return new Response(JSON.stringify({ scanned: true }), { status: 200 })
      if (String(url).includes('/readyz')) return new Response(JSON.stringify({ ok: true }), { status: 200 })
      if (String(url).includes('/v1/latticedb/manifest')) return new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 })
      if (String(url).includes('/v1/license/status')) {
        return new Response(JSON.stringify({ mode: 'dev', notice: 'for testing' }), { status: 200 })
      }
      if (String(url).includes('/v1/latticedb/route')) {
        return new Response(
          JSON.stringify({ candidates: [{ lattice_id: 'G-000001', score: 0.91 }] }),
          { status: 200 }
        )
      }
      if (String(url).includes('/v1/latticedb/compose')) {
        return new Response(JSON.stringify({ context_pack: { receipts: {} } }), { status: 200 })
      }
      return new Response('not found', { status: 404 })
    })

    render(<App />)

        const runBtn = screen.getByRole('button', { name: /^Run$/ })
        fireEvent.click(runBtn)

    await screen.findByText(/Context Pack/i)

    const verifyBtn = await screen.findByRole('button', { name: /Verify against DB root/i })
    fireEvent.click(verifyBtn)

    await screen.findByText(/No composite receipt to verify/i)
  })

  it('shows error message if DB receipt fetch fails', async () => {
    ;(g.fetch as any) = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/v1/db/scan')) return new Response(JSON.stringify({ scanned: true }), { status: 200 })
      if (String(url).includes('/readyz')) return new Response(JSON.stringify({ ok: true }), { status: 200 })
      if (String(url).includes('/v1/latticedb/manifest')) return new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 })
      if (String(url).includes('/v1/license/status')) {
        return new Response(JSON.stringify({ mode: 'dev', notice: 'for testing' }), { status: 200 })
      }
      if (String(url).includes('/v1/latticedb/route')) {
        return new Response(
          JSON.stringify({
            candidates: [
              { lattice_id: 'G-000001', score: 0.91 },
            ],
          }),
          { status: 200 }
        )
      }
      if (String(url).includes('/v1/latticedb/compose')) {
        return new Response(
          JSON.stringify({ context_pack: { receipts: { composite: { db_root: 'zzz' } } } }),
          { status: 200 }
        )
      }
      if (String(url).includes('/v1/db/receipt')) {
        return new Response('nope', { status: 500 })
      }
      return new Response('not found', { status: 404 })
    })

    render(<App />)

    const runBtns = screen.getAllByRole('button', { name: /Run/i })
      const runBtn = screen.getByRole('button', { name: /^Run$/ })
      fireEvent.click(runBtn)

    await screen.findByText(/Context Pack/i)

    const verifyBtn = await screen.findByRole('button', { name: /Verify against DB root/i })
    fireEvent.click(verifyBtn)

    await screen.findByText(/Failed to fetch DB receipt/i)
  })
})
