// File: tailwind.config.mjs  (add colors; if you use .cjs, see note below)
import { defineConfig } from 'tailwindcss'

export default defineConfig({
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        brandPaper: '#f4e3d1',
        brandYellow: '#ffd600',
      },
    },
  },
  plugins: [],
})
