// File: astro.config.mjs
import { defineConfig } from 'astro/config';

// Auto base path for GitHub Pages preview (e.g., /oveFI/)
const repo = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
const onPages = !!process.env.GITHUB_ACTIONS;
const base = onPages && repo ? `/${repo}/` : '/';

export default defineConfig({
  site: 'https://holminid.github.io', // ok for preview; production will be your own domain
  base,
});
