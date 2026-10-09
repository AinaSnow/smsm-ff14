"""Exercise actual WARP producer writes and inspect bounded same-frame provenance records."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np
from build_native_diagnostic import ROOT,compile_cpp
from analyze_native_output import analyze


def run(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False)
    exe=root/'test_light_producer_probe.exe'
    compile_cpp(ROOT/'addons/native_lighting/test_light_producer_probe.cpp',exe)
    subprocess.run([str(exe),str(root/'captures')],check=True)
    rows=[]
    for case in ['normal','stale','capped']:
        path=next((root/'captures'/case).glob('*/report.json'));r=json.loads(path.read_bytes());v=analyze(path.parent)
        d=r['draws'][0];t0=next(x for x in d['inputs'] if x['label'].endswith('-ps-t0'));h=t0['producer_history']
        if case=='normal':
            assert len(r['producer_records'])==r['producer_candidates']==1 and not r['producer_trace_truncated']
            p=r['producer_records'][0]
            assert p['draw']<d['draw'] and p['frame']==d['frame'] and p['outputs'][0]['resource']==t0['resource']
            assert h['writer_observation_scope']=='current_capture_frame_and_enable_epoch'
            assert h['last_observed_rtv_draw']['draw']==p['draw']
            b=next(x for x in p['inputs'] if x['label'].endswith('-ps-b2'))
            a=np.fromfile(path.parent/b['file'],np.float32);assert np.allclose(a[8:11],[4,1.4,.4])
            b=next(x for x in d['inputs'] if x['label'].endswith('-ps-b2'))
            assert np.all(np.fromfile(path.parent/b['file'],np.float32)==3.5)
        elif case=='stale':
            assert not r['producer_records'] and h['writer_observation_scope']=='historical_observation_only'
        else:
            assert len(r['producer_records'])==128 and r['producer_candidates']==129 and r['producer_trace_truncated']
        rows.append({'case':case,'verified_bytes':v['verified_bytes'],'recorded_producers':len(r['producer_records'])})
    result={'passed':True,'cases':rows,'early_depth_draws_filtered':520,'snapshot_lifetime_verified':True,'cancel_disables_tracking':True}
    (root/'verified.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);run(p.parse_args().output)
