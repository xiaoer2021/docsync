
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    server: {
        port: 5273,
        proxy: {
            '/api': {
                target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
            '/health': {
                target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
        chunkSizeWarningLimit: 1200,
    },
});
