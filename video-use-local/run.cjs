const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');

const local = __dirname;
const root = path.resolve(local, '..', 'video-use');
const python = process.env.VIDEO_WORKFLOW_PYTHON || path.join(root, '.venv', 'Scripts', 'python.exe');
const env = {...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', MPLCONFIGDIR: path.join(local, '.cache', 'matplotlib')};
const oldPath = process.env.Path || process.env.PATH || '';
const candidates = [];
if (env.VIDEO_USE_FFMPEG_PATH) candidates.push(env.VIDEO_USE_FFMPEG_PATH);
for (const folder of oldPath.split(path.delimiter)) candidates.push(path.join(folder, 'ffmpeg.exe'));
if (env.LOCALAPPDATA) {
  const packages = path.join(env.LOCALAPPDATA, 'Microsoft', 'WinGet', 'Packages');
  if (fs.existsSync(packages)) {
    for (const item of fs.readdirSync(packages, {withFileTypes: true})) {
      if (!item.isDirectory() || !item.name.startsWith('Gyan.FFmpeg_')) continue;
      const folder = path.join(packages, item.name);
      for (const version of fs.readdirSync(folder, {withFileTypes: true})) {
        if (version.isDirectory()) candidates.push(path.join(folder, version.name, 'bin', 'ffmpeg.exe'));
      }
    }
  }
}
candidates.push(path.resolve(local, '..', 'remotion', 'node_modules', '@remotion', 'compositor-win32-x64-msvc', 'ffmpeg.exe'));
const ffmpeg = candidates.find((candidate) => fs.existsSync(candidate));
if (!ffmpeg || !fs.existsSync(python)) {
  console.error('Python environment or FFmpeg is missing. Resume installation before using this launcher.');
  process.exit(1);
}
for (const key of Object.keys(env)) if (/^path$/i.test(key)) delete env[key];
env.Path = [path.dirname(ffmpeg), path.dirname(python), oldPath].join(path.delimiter);
env.VIRTUAL_ENV = path.join(root, '.venv');
env.VIDEO_USE_ROOT = root;

const [command, ...args] = process.argv.slice(2);
const helpers = ['render', 'grade'];
let binary = python;
let params;
if (helpers.includes(command)) params = [path.join(root, 'helpers', command + '.py'), ...args];
else if (command === 'doctor') params = [path.join(local, 'doctor.py'), ...args];
else if (command === 'ffmpeg' || command === 'ffprobe') {
  binary = command === 'ffmpeg' ? ffmpeg : path.join(path.dirname(ffmpeg), 'ffprobe.exe');
  params = args;
} else {
  console.log('Video Use: ' + root);
  console.log('Usage: node video-use-local/run.cjs <helper> [arguments]');
  console.log('Helpers: ' + helpers.join(', '));
  console.log('Setup: doctor, ffmpeg, ffprobe');
  process.exit(command ? 1 : 0);
}
const child = spawn(binary, params, {env, stdio: 'inherit', windowsHide: true});
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code) => { process.exitCode = code ?? 1; });
