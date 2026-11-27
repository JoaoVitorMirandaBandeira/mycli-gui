import {createHash} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const directory = fileURLToPath(new URL('.', import.meta.url));
const htmlFile = new URL('../../my-gui/index.html', import.meta.url);
const start = '<!-- BEGIN SQL EDITOR BUNDLE -->';
const end = '<!-- END SQL EDITOR BUNDLE -->';
const result = await build({
  absWorkingDir: directory,
  entryPoints: ['editor.mjs'],
  bundle: true,
  minify: true,
  format: 'iife',
  globalName: 'SqlEditor',
  target: 'chrome100',
  legalComments: 'none',
  metafile: true,
  write: false
});
const bundle = result.outputFiles[0].text.trimEnd();
if (/<\/script/i.test(bundle)) throw new Error('O bundle fecha a tag script');

const packages = new Set();
for (const input of Object.keys(result.metafile.inputs)) {
  const name = /^node_modules\/((?:@[^/]+\/)?[^/]+)\//.exec(input)?.[1];
  if (name) packages.add(name);
}
const notices = new Set();
for (const name of [...packages].sort()) {
  const license = await readFile(new URL('node_modules/' + name + '/LICENSE', import.meta.url), 'utf8');
  notices.add(license.trim());
}

const hash = createHash('sha256').update(bundle).digest('hex');
const generated = start + '\n<script>\n/*!\n' + [...notices].join('\n\n') +
  '\n*/\n// SHA-256: ' + hash + '\n' + bundle + '\n</script>\n' + end;
const html = await readFile(htmlFile, 'utf8');
const from = html.indexOf(start);
const to = html.indexOf(end, from);
if (from < 0 || to < 0) throw new Error('Marcadores do bundle ausentes em index.html');

if (process.argv.includes('--check')) {
  if (html.slice(from, to + end.length) !== generated) {
    console.error('O bundle diverge do build. Rode npm run build --prefix tools/sql-editor.');
    process.exitCode = 1;
  }
} else {
  await writeFile(htmlFile, html.slice(0, from) + generated + html.slice(to + end.length));
}
