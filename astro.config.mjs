// astro.config.mjs
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import { fileURLToPath } from 'node:url'; // <-- add this

export default defineConfig({
  site: 'https://ove.fi',
  output: 'static',
  integrations: [mdx(), tailwind({ applyBaseStyles: false })],
  vite: {
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }, // <-- add this
    },
  },
});
