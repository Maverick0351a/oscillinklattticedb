import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'

// Mock react-dom/client createRoot to observe renders
vi.mock('react-dom/client', async () => {
  const actual = await vi.importActual<typeof import('react-dom/client')>('react-dom/client')
  return {
    ...actual,
    createRoot: vi.fn(() => ({ render: vi.fn() })),
  }
})

beforeAll(() => {
  // Mock global fetch used by App's license effect
  ;(globalThis as any).fetch = vi.fn(async () => new Response(JSON.stringify({ mode: 'dev', notice: '' }), { status: 200 }))
})

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>'
})

describe('main.tsx entrypoint', () => {
  it('mounts the App into #root', async () => {
    const { createRoot } = await import('react-dom/client') as any
    await import('./main')
    expect(createRoot).toHaveBeenCalled()
  })
})
