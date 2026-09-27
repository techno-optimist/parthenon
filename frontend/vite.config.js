import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// Where the city stands on the site: '/' on the owner's own machine (the
// default), '/parthenon/' on projectforty2.ai (VITE_BASE=/parthenon/). The
// page reads it as import.meta.env.BASE_URL (src/parthenon/base.js).
const normalizeBase = (value) => {
  let b = String(value || '').trim()
  if (!b || b === '.' || b === './') return '/'
  if (!b.startsWith('/')) b = `/${b}`
  if (!b.endsWith('/')) b = `${b}/`
  return b
}
const base = normalizeBase(process.env.VITE_BASE)

const backend = {
  target: 'http://localhost:5001',
  changeOrigin: true,
  secure: false
}

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@locales': path.resolve(__dirname, '../locales')
    }
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': backend,
      // Under a base, the page asks <base>api/...: the local backend answers at /api.
      ...(base === '/' ? {} : {
        [`${base}api`]: { ...backend, rewrite: (p) => p.slice(base.length - 1) }
      })
    }
  }
})
