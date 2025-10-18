import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Auto-cleanup JSDOM after each test
afterEach(() => {
	cleanup()
})
