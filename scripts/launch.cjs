// Resolve tool locations once; never copy old project footage or approvals.
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const configFile = path.join(root, 'runtime.local.json');
let config = {};
try { if (fs.existsSync(configFile)) config = JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^\uFEFF/, '')); }
catch (e) { console.error('Invalid runtime.local.json: ' + e.message); process.exit(2); }
const env = {...process.env, PYTHONUTF8:'1', PYTHONIOENCODING:'utf-8', PYTHONDONTWRITEBYTECODE:'1'};
const resolve = p => p && (path.isAbsolute(p) ? p : path.resolve(root,p));
const pythonOptions = [env.VIDEO_WORKFLOW_PYTHON, resolve(config.python), path.join(root,'.venv','Scripts','python.exe'), path.join(root,'video-use','.venv','Scripts','python.exe')].filter(Boolean);
let python = pythonOptions.find(p=>fs.existsSync(p));
if (!python) {
  const probe=spawnSync('python',['-c','import sys; print(sys.executable)'],{encoding:'utf8',windowsHide:true,timeout:5000});
  if(probe.status===0 && fs.existsSync(probe.stdout.trim())) python=probe.stdout.trim();
}
if (!python) { console.error('Set python in runtime.local.json to an existing Python 3.10+ interpreter.'); process.exit(2); }
env.VIDEO_WORKFLOW_PYTHON=python;
if(config.ffmpeg && !env.VIDEO_USE_FFMPEG_PATH) env.VIDEO_USE_FFMPEG_PATH=resolve(config.ffmpeg);
if(config.hypit_dir && !env.VIDEO_WORKFLOW_HYPIT_DIR) env.VIDEO_WORKFLOW_HYPIT_DIR=resolve(config.hypit_dir);
const args=process.argv.slice(2), command=args[0];
if(!command) { console.log('Usage: 工作流工具.cmd doctor|init|context|inventory|reference|reference-detail|storyboard|status|approve|render-preview|render-final|metrics [arguments]');process.exit(0); }
function run(binary, params, options={}) {
 return spawnSync(binary,params,{env,windowsHide:true,stdio:'inherit',...options});
}
if(command==='doctor') {
 const checks=[];
 const py=run(python,['-c','import sys, PIL; assert sys.version_info >= (3,10); print(sys.version.split()[0]+"; Pillow "+PIL.__version__)'],{encoding:'utf8',stdio:'pipe',timeout:15000});
 checks.push({tool:'Python/Pillow',ok:py.status===0,detail:(py.stdout||py.stderr||py.error?.message||'').trim()});
 for(const name of ['ffmpeg','ffprobe']){
  const result=run(process.execPath,[path.join(root,'video-use-local','run.cjs'),name,'-version'],{encoding:'utf8',stdio:'pipe',timeout:15000});
  checks.push({tool:name,ok:result.status===0,detail:(result.stdout||result.stderr||result.error?.message||'').split('\n')[0]});
 }
 const hypitDir=env.VIDEO_WORKFLOW_HYPIT_DIR||path.join(root,'hypit-local','node_modules','@hypit','hypit');
 let hypitVersion=null;try{hypitVersion=JSON.parse(fs.readFileSync(path.join(hypitDir,'package.json'),'utf8')).version;}catch{}
 console.log(JSON.stringify({checks,basic_ready:checks.every(c=>c.ok),optional_hypit:{installed_version:hypitVersion,adapter_expected_version:'0.3.1',full_reference_run_checked:false},optional_transcription:'Not checked; requires actual ASR/alignment',optional_animation:'Not checked; choose per project',python,config_file:configFile},null,2));
 process.exit(checks.every(c=>c.ok)?0:2);
}
// For isolated synthetic tests and one-off project scripts, with the same runtime env.
const result=command==='python'?run(python,args.slice(1)):run(python,['-B',path.join(root,'workflow-kit','efficient.py'),...args]);
if(result.error) console.error(result.error.message);
process.exit(result.status??2);
