// Vite build config for the React renderer. In dev it allows the inline styles Vite injects,
// and `base: './'` lets Electron load the built files from disk.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'dev-csp-styles',
      transformIndexHtml(html, context) {
        if (context.server) {
          return html.replace(
            "script-src 'self'; connect-src",
            "script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src",
          )
        }
        return html
      },
    },
  ],
  base: './',
})
