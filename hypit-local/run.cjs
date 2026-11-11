const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');

const entry = path.join(process.env.VIDEO_WORKFLOW_HYPIT_DIR || path.join(__dirname, 'node_modules', '@hypit', 'hypit'), 'bin', 'hypit.mjs');
if (!fs.existsSync(entry)) {
  console.error('Hypit is not installed at ' + entry);
  process.exit(2);
}
const env = {...process.env};
const oldPath = env.Path || env.PATH || '';
const candidates = [];
if (env.VIDEO_USE_FFMPEG_PATH) candidates.push(env.VIDEO_USE_FFMPEG_PATH);
for (const folder of oldPath.split(path.delimiter)) {
  if (folder) candidates.push(path.join(folder, 'ffmpeg.exe'));
}
if (env.LOCALAPPDATA) {
  const base = path.join(env.LOCALAPPDATA, 'Microsoft', 'WinGet', 'Packages');
  if (fs.existsSync(base)) {
    for (const item of fs.readdirSync(base, {withFileTypes: true})) {
      if (!item.isDirectory() || !item.name.startsWith('Gyan.FFmpeg_')) continue;
      const folder = path.join(base, item.name);
      for (const version of fs.readdirSync(folder, {withFileTypes: true})) {
        if (version.isDirectory()) candidates.push(path.join(folder, version.name, 'bin', 'ffmpeg.exe'));
      }
    }
  }
}
const ffmpeg = candidates.find(file => fs.existsSync(file) && fs.existsSync(path.join(path.dirname(file), 'ffprobe.exe')));
if (ffmpeg) {
  for (const key of Object.keys(env)) if (/^path$/i.test(key)) delete env[key];
  env.Path = [path.dirname(ffmpeg), oldPath].join(path.delimiter);
}
const child = spawn(process.execPath, [entry, ...process.argv.slice(2)], {
  cwd: process.cwd(), env, stdio: 'inherit', windowsHide: true
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
