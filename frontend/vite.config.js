import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const proxy = Object.fromEntries(
  [['agent', 8002], ['policy', 8001], ['persistence', 8003]].map(([service, port]) => [
    `/api/${service}`,
    {
      target: `http://127.0.0.1:${port}`,
      changeOrigin: true,
      rewrite: (path) => path.replace(`/api/${service}`, ''),
    },
  ]),
)

export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true, proxy, allowedHosts: ['7b83-118-140-62-215.ngrok-free.app'] },
  preview: { port: 5173, strictPort: true, proxy, allowedHosts: ['7b83-118-140-62-215.ngrok-free.app'] },
})
