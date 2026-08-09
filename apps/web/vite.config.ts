/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: mode === 'user-desktop' ? {
    outDir: 'dist-user',
    emptyOutDir: true,
    rollupOptions: { input: fileURLToPath(new URL('./user.html', import.meta.url)) },
  } : undefined,
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    clearMocks: true,
  },
}));
