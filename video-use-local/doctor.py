import json, shutil, subprocess, sys
from PIL import __version__ as pillow_version
checks = {'python':sys.version.split()[0], 'pillow':pillow_version}
for name in ('ffmpeg','ffprobe'):
    found=shutil.which(name)
    if not found:
        raise SystemExit('Missing '+name)
    result=subprocess.run([found,'-version'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    checks[name]=result.stdout.splitlines()[0]
print(json.dumps(checks,ensure_ascii=False))
