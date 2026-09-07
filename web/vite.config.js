import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 設定文件：https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 同時監聽區域網路（LAN），這樣才能用手機開啟開發中的頁面
    port: 5173,
  },
})
