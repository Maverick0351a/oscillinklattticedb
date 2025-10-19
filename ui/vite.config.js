import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: '127.0.0.1' },
  preview: { port: 8081, host: '0.0.0.0' },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.ts',
    // Only run unit tests; exclude Playwright e2e specs from Vitest
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['e2e/**/*', 'node_modules', 'dist'],
    coverage: {
      reporter: ['text', 'lcov', 'json'],
      exclude: ['e2e/**/*']
    },
  }
})