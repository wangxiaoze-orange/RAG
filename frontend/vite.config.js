import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器：/api 代理到后端 8000
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,     // 监听所有网卡（IPv4+IPv6），允许局域网/服务器外部访问
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // SSE 需要关闭缓冲
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['Cache-Control'] = 'no-cache'
          })
        }
      }
    }
  }
})
