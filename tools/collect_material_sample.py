"""Collect one bounded native sample, optionally within this caller's warm lifecycle session."""
import argparse
import json
from pathlib import Path
import re
import shutil
import time
from request_native_ambient import request
from analyze_native_output import analyze


def collect(game,output,shader,vertex=None,elements=None,skip=0,bridge=None,stage=None):
    native=game/'SMSM-native-captures';command=native/'ambient-command.txt';statusfile=native/'ambient-status.json'
    if output.exists():raise ValueError('Use a new immutable output directory')
    def check_lamp():
        if stage is None:return
        if bridge is None:raise ValueError('Lifecycle control directory required')
        state=json.loads((bridge/'status.json').read_bytes())
        if not state['running'] or state['ownedStage']!=stage or not state['status'].startswith('Lifecycle warm lamp'):
            raise ValueError('Owned warm lamp changed or expired; sample invalid')
    check_lamp()
    s=json.loads(statusfile.read_bytes())
    if any(s[k] for k in ['enabled','coverage_enabled','output_audit_active']) or command.exists():raise ValueError('Native capture/effect already active')
    previous=s['output_audit_directory'];lock=native/'.smsm-m2-session.lock';lease=None;submitted=False
    action='probe' if vertex is not None else 'sample'
    text=f'probe {shader} {elements} {vertex}' if action=='probe' else f'sample {shader} {skip}'
    try:
        if stage is None:lease=lock.open('xb')
        elif not lock.exists():raise ValueError('Lifecycle bridge no longer owns capture coordination')
        submitted=True
        request(game,action,shader,skip=skip,vertex=vertex,elements=elements)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            check_lamp()
            ready=False
            try:
                s=json.loads(statusfile.read_bytes());name=s['output_audit_directory']
                if name!=previous and re.fullmatch(r'output-audit-\d+-\d+',name) and not s['output_audit_active'] and not command.exists():
                    report=json.loads((native/name/'report.json').read_bytes());ready=True
            except (OSError,json.JSONDecodeError):pass
            if ready:
                if report['status']!='complete' or report['mode']!=action or report['selected_shader']!=shader:raise ValueError('Unexpected native report')
                check_lamp();output.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(native/name,output)
                verified=analyze(output);check_lamp()
                (output/'verified.json').write_text(json.dumps(verified,indent=2)+'\n',encoding='utf-8')
                return report,verified
            time.sleep(.1)
        raise RuntimeError('Bounded material capture timed out')
    finally:
        try:
            if submitted:
                if command.exists() and command.read_text().strip()==text:command.unlink()
                elif not command.exists():
                    current=json.loads(statusfile.read_bytes())
                    if current['output_audit_directory']!=previous and current['output_audit_active']:request(game,'off')
        finally:
            if lease is not None:lease.close();lock.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('game',type=Path);p.add_argument('output',type=Path);p.add_argument('--shader',required=True)
    p.add_argument('--vertex');p.add_argument('--elements',type=int);p.add_argument('--skip',type=int,default=0)
    p.add_argument('--bridge',type=Path);p.add_argument('--stage')
    a=p.parse_args();r,v=collect(a.game,a.output,a.shader,a.vertex,a.elements,a.skip,a.bridge,a.stage)
    print(json.dumps({'draws':r['observed_target_draws'],'verified_bytes':v['verified_bytes'],'output':str(a.output)}))
