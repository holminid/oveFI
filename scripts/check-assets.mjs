import { readdir, readFile, stat, access } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const DIST = resolve('dist');
const missing = [];
const imgAltErrors = [];

async function *walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield *walk(full);
    else if (entry.isFile()) yield full;
  }
}
function extractAttrs(html, tag, attr) {
  const re = new RegExp(`<${tag}[^>]*?${attr}="([^"]+)"[^>]*>`, 'gi');
  const out = []; let m;
  while ((m = re.exec(html))) out.push(m[1]);
  return out;
}
function normalizePath(p) {
  const noHash = p.split('#')[0];
  const noQuery = noHash.split('?')[0];
  return noQuery;
}
async function existsWebPath(urlPath) {
  if (!urlPath.startsWith('/')) return true;
  const local = join(DIST, urlPath.slice(1));
  try {
    const s = await stat(local).catch(() => null);
    if (s && s.isFile()) return true;
    if (s && s.isDirectory()) {
      await access(join(local, 'index.html'));
      return true;
    }
    await access(local + '.html');
    return true;
  } catch { return false; }
}

for await (const file of walk(DIST)) {
  if (!file.endsWith('.html')) continue;
  const html = await readFile(file, 'utf8');

  const imgTags = html.match(/<img\b[^>]*>/gi) || [];
  for (const tag of imgTags) {
    const hasAlt = /\balt=\"[^\"]*\"/i.test(tag);
    if (!hasAlt) imgAltErrors.push({ file, tag });
  }

  const hrefs = extractAttrs(html, 'a', 'href');
  const imgSrcs = extractAttrs(html, 'img', 'src');
  const sources = extractAttrs(html, 'source', 'src');
  const posters = extractAttrs(html, 'video', 'poster');
  const links = extractAttrs(html, 'link', 'href');
  const scripts = extractAttrs(html, 'script', 'src');

  const urls = [...hrefs, ...imgSrcs, ...sources, ...posters, ...links, ...scripts]
    .map(normalizePath)
    .filter(u => u && !u.startsWith('http') && !u.startsWith('mailto:') && !u.startsWith('tel:'));

  for (const u of urls) {
    const ok = await existsWebPath(u);
    if (!ok) missing.push({ file, url: u });
  }
}

if (imgAltErrors.length) {
  console.error(`\n❌ Images missing alt (${imgAltErrors.length}):`);
  for (const e of imgAltErrors.slice(0, 20)) console.error(` - ${e.file}: ${e.tag}`);
}
if (missing.length) {
  console.error(`\n❌ Missing assets/internal links (${missing.length}):`);
  for (const m of missing.slice(0, 20)) console.error(` - ${m.file} → ${m.url}`);
}
if (imgAltErrors.length || missing.length) {
  console.error('\nFailing CI due to issues above.');
  process.exit(1);
} else {
  console.log('✅ Asset & link checks passed.');
}
