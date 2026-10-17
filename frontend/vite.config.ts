import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
    plugins: [react()],
    base: './',
    resolve: {
        alias: {
            // The platform SDK is injected at deploy time on the appdeploy host and
            // is not on the public npm registry, so local builds, CI and GitHub
            // Pages resolve it to the in-repo implementation instead.
            '@appdeploy/client': fileURLToPath(new URL('./src/lib/appdeploy-client.ts', import.meta.url)),
        },
    },
    build: {
        outDir: process.env.APPDEPLOY_VITE_OUT_DIR || 'dist',
        sourcemap: process.env.APPDEPLOY_VITE_SOURCEMAP === 'hidden' ? 'hidden' : false,
        rollupOptions: {
            maxParallelFileOps: 128,
        },
    },
});
