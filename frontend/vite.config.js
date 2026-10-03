import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Port 5173 is the frontend_origin the backends allow for CORS.
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true },
})
