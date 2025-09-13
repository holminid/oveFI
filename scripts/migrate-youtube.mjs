import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const ROOT = resolve('.');
const SEED_PATH = join(ROOT, 'scripts', 'videos.seed.json');
const WORKS_DIR = join(ROOT, 'src', 'content', 'works');
const PUBLIC_WORKS_DIR = join(ROOT, 'public', 'works');
const NO_FETCH = process.argv.includes('--no-fetch');

function slugify(str) {
  return String(str).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '').slice(0, 80);
}
function parseYouTubeId(url) {
  try {
    const u = new URL(url);
    if (u.hostname === 'youtu.be') return u.pathname.slice(1);
    if (u.hostname.includes('youtube.com')) {
      if (u.pathname === '/watch') return u.searchParams.get('v');
      const m = u.pathname.match(/\/embed\/([\w-]+)/);
      if (m) return m[1];
    }
  } catch {}
  return null;
}
async function ensureDir(p) { try { await mkdir(p, { recursive: true }); } catch {} }
async function exists(p) { try { await access(p); return true; } catch { return false; } }

async function download(url, dest) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to download ${url}`);
  await ensureDir(dirname(dest));
  const out = createWriteStream(dest);
  await new Promise((resolve, reject) => {
    res.body.pipe(out);
    res.body.on('error', reject);
    out.on('finish', resolve);
  });
}
function frontmatter({ title, date, coverWeb, summary, id }) {
  return `---\n` +
    `title: ${title}\n` +
    `date: ${date}\n` +
    `mediaType: video\n` +
    `cover:\n` +
    `  src: ${coverWeb}\n` +
    `  width: 1280\n` +
    `  height: 720\n` +
    `  alt: ${title} — cover frame\n` +
    `images: []\n` +
    `videos: []\n` +
    `externalVideos:\n` +
    `  - kind: youtube\n    id: ${id}\n    title: ${title}\n    aspect: 16:9\n` +
    (summary ? `summary: >-\n  ${String(summary).replace(/\n/g, '\n  ')}\n` : '') +
    `---\n\n`;
}

const seed = JSON.parse(await readFile(SEED_PATH, 'utf8'));
await ensureDir(WORKS_DIR);
await ensureDir(PUBLIC_WORKS_DIR);

for (const item of seed) {
  const id = parseYouTubeId(item.url);
  if (!id) throw new Error(`Invalid YouTube URL: ${item.url}`);

  let title = (item.title || '').trim();
  let thumb = `https://img.youtube.com/vi/${id}/maxresdefault.jpg`;
  if (!NO_FETCH) {
    try {
      const o = await fetch(`https://www.youtube.com/oembed?url=https://youtu.be/${id}&format=json`).then(r => r.json());
      title ||= o.title; thumb = o.thumbnail_url || thumb;
    } catch {}
  }
  title ||= `Untitled (${id})`;

  const slug = slugify(item.slug || title);
  const pubDir = join(PUBLIC_WORKS_DIR, slug);
  const coverPath = join(pubDir, 'cover.jpg');
  const coverWeb = `/works/${slug}/cover.jpg`;

  if (!(await exists(coverPath))) {
    for (const u of [thumb, `https://img.youtube.com/vi/${id}/maxresdefault.jpg`, `https://img.youtube.com/vi/${id}/hqdefault.jpg`]) {
      try { await download(u, coverPath); break; } catch {}
    }
  }

  const mdxPath = join(WORKS_DIR, `${slug}.mdx`);
  if (await exists(mdxPath)) { console.log(`↷ Skip existing: ${slug}.mdx`); continue; }

  const fm = frontmatter({
    title,
    date: item.date || '2020-01-01',
    coverWeb,
    summary: item.summary || item.description || '',
    id
  });

  const body = [item.description, item.detail].filter(Boolean).join('\n\n');
  await writeFile(mdxPath, fm + (body ? body + '\n' : ''), 'utf8');
  console.log(`✓ Wrote ${slug}.mdx`);
}
console.log('Done.');
