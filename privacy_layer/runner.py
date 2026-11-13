"""Offline skill execution. Raw outputs are owner-only, never MCP tool content.

Seatbelt is a required second boundary, not a substitute for output confinement.
Only self-contained Python and hash-pinned pure-Python wheel dependencies run.
"""
import base64,json,os,resource,signal,stat,subprocess,sys,tempfile
from pathlib import Path
from .core import Denied
from .skills import safe_path,unzip,MAX_PACKAGE

MAX_OUTPUT=2*1024*1024

def limits():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_OUTPUT,MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    # No descendants; the OS policy independently denies process-fork.
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))

def execute(package,script,inputs,timeout=20):
    if sys.platform!='darwin' or not Path('/usr/bin/sandbox-exec').exists():raise Denied('Local execution needs the supported Mac isolation service. Nothing was run.')
    if script not in package['scripts'] or not script.endswith('.py'):raise Denied('This version runs Python scripts. Other skill resources can be read, but their scripts are not executed.')
    with tempfile.TemporaryDirectory(prefix='airlock-action-') as temp:
        root=Path(temp).resolve();pkg=root/'skill';out=root/'output';scratch=root/'tmp';deps=root/'dependencies'
        for p in (pkg,out,scratch,deps):p.mkdir(mode=0o700)
        for name,value in package['files'].items():
            dest=pkg/safe_path(name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(base64.b64decode(value,validate=True))
        expanded=0;seen=set()
        for wheel in package['dependencies']:
            for name,raw in unzip((pkg/wheel).read_bytes()).items():
                expanded+=len(raw)
                if expanded>MAX_PACKAGE or name.casefold() in seen:raise Denied('Bundled dependencies overlap or expand beyond the local limit.')
                seen.add(name.casefold());dest=deps/safe_path(name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        (root/'input.json').write_text(json.dumps(inputs,ensure_ascii=False))
        runner=root/'run.py'
        runner.write_text('import os,runpy,sys\nfrom pathlib import Path\nr=Path(__file__).parent\nsys.path[:0]=[str(r/"dependencies"),str(r/"skill/scripts")]\nos.chdir(r/"skill")\nrunpy.run_path(str(r/"skill"/'+repr(script)+'),run_name="__main__")\n')
        python=Path(sys.executable).resolve();base=Path(sys.base_prefix).resolve()
        quote=lambda p:json.dumps(str(p))
        profile='(version 1)\n(deny default)\n(allow file-read* (literal "/"))\n(allow process-exec (literal '+quote(python)+'))\n(allow signal (target self))\n(allow sysctl-read)\n'
        for p in ('/System/Library','/usr/lib',str(base),str(root)):
            profile+='(allow file-read* (subpath '+quote(p)+'))\n'
        for p in ('/dev/null','/dev/random','/dev/urandom','/private/var/db/timezone'):
            profile+='(allow file-read* (subpath '+quote(p)+'))\n'
        for p in (out,scratch):profile+='(allow file-write* (subpath '+quote(p)+'))\n'
        policy=root/'policy.sb';policy.write_text(profile)
        env={'PATH':'/usr/bin:/bin','HOME':str(scratch),'TMPDIR':str(scratch),'LANG':'en_US.UTF-8','AIRLOCK_INPUT':str(root/'input.json'),'AIRLOCK_OUTPUT':str(out)}
        # Pipe output is redirected to a bounded file, never unbounded RAM or logs.
        capture=root/'capture.txt'
        with capture.open('wb') as stdout:
            p=subprocess.Popen(['/usr/bin/sandbox-exec','-f',str(policy),str(python),'-I','-S','-B',str(runner)],stdin=subprocess.DEVNULL,stdout=stdout,stderr=stdout,env=env,cwd=pkg,start_new_session=True,preexec_fn=limits)
            timed_out=False
            try:p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(p.pid,signal.SIGKILL);p.wait()
        outputs=[];total=0
        for f in sorted(out.rglob('*')):
            if len(outputs)>=32:break
            # Never follow output links, including links in parent directories.
            if any(x.is_symlink() for x in [f,*f.relative_to(out).parents] if x.is_absolute()):continue
            if any(x.is_symlink() for x in [f,*list(f.parents)[:len(f.relative_to(out).parts)-1]]):continue
            st=f.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>MAX_OUTPUT:continue
            raw=f.read_bytes();total+=len(raw)
            if total>MAX_OUTPUT:break
            outputs.append({'name':f.relative_to(out).as_posix(),'content':base64.b64encode(raw).decode()})
        raw=capture.read_bytes()[:MAX_OUTPUT]
        if raw:outputs.append({'name':'execution-log.txt','content':base64.b64encode(raw).decode()})
        return {'status':'timed_out' if timed_out else 'completed' if p.returncode==0 else 'failed','files':outputs}
