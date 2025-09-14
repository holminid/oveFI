// File: astro.config.mjs
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

const repo = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
const onPages = !!process.env.GITHUB_ACTIONS;
const base = onPages && repo ? `/${repo}/` : '/';

export default defineConfig({
  site: 'https://holminid.github.io', // preview only
  base,
  integrations: [mdx()],
});
