"""Draw the exact H2 shader with its real Texture1D control resource."""
import argparse
from pathlib import Path
import numpy as np
import copy
from offline_render import render
from build_tone_highlights import BINARY
from manage_preview import encoded, read_package, digest, RECEIPT


def validate(base, h1, h2, output, runtime_check=False):
    for package in (base,h1,h2): read_package(package)
    output.mkdir(parents=True, exist_ok=False)
    width,height=256,64
    texture=np.ones((height,width,4),dtype=np.float32)
    ramp=np.geomspace(.001,16,width).astype(np.float32)
    texture[:,:,:3]=ramp[None,:,None]*np.array([1,.65,.45],dtype=np.float32)
    texture[:,:,3]=np.linspace(0,1,width)
    lut=np.ones((1,256,4),dtype=np.float32)
    constants={0:[[0,1,1,0]],1:[[0,0,1,0],[0,1,0,0]]}
    def draw(package,name,controls=None):
        resources={}
        if controls is not None:
            params=np.zeros((8,4),dtype=np.float32); params[7,:2]=controls
            resources={120:params}
        return render(package/BINARY,output/name,width,height,textures={0:texture,1:lut},
                      constants=constants,textures1d=resources)[0,0]
    baseline=draw(base,'baseline'); high=draw(h1,'h1')
    off=draw(h2,'off',(0,0)); on=draw(h2,'on',(1,0)); back=draw(h2,'back',(0,0))
    assert np.array_equal(off,baseline), 'OFF must exactly reproduce accepted r10 output'
    assert np.array_equal(on,high), 'ON must exactly reproduce H1 output'
    assert np.array_equal(back,baseline), 'Return to OFF must restore baseline'
    labels=[draw(h2,'label-off',(0,1)),draw(h2,'label-on',(1,1))]
    mask=np.zeros((height,width),dtype=bool); mask[24:46,24:72]=True
    for labelled,reference in zip(labels,(off,on)):
        assert np.array_equal(labelled[~mask],reference[~mask]), 'Label changed pixels outside its bounds'
        assert np.array_equal(labelled[:,:,3],reference[:,:,3]), 'Label changed alpha'
        assert np.isfinite(labelled).all()
    assert not np.array_equal(labels[0][mask],labels[1][mask]), 'Mode labels must differ'
    report={'status':'pass','off_equals_r10_exactly':True,'on_equals_h1_exactly':True,
            'return_to_off_exact':True,'label_bounds':[24,24,72,46],'label_alpha_unchanged':True,
            'control_resource':'Texture1D float4 t120[7].xy',
            'note':'Separate WARP draws verify shader states; actual game keyboard input remains unverified',
            'game_keyboard_verified':False}
    if runtime_check:
        original, _ = read_package(h2)
        results=[]
        for mode, expected in ((0,labels[0]),(1,labels[1])):
            # An isolated startup fixture: only the initial x7 value differs.
            # No synthetic t120 binding: 3DMigoto must allocate/populate it.
            package=output/f'runtime-fixture-{mode}'; package.mkdir()
            manifest=copy.deepcopy(original)
            for name in manifest['files']:
                data=(h2/name).read_bytes()
                if name=='d3dx.ini': data=data.replace(b'x7 = 0\ny7 = 1',f'x7 = {mode}\ny7 = 1'.encode())
                path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                manifest['files'][name]=digest(data)
            manifest['isolated_test_fixture']=True
            (package/RECEIPT).write_bytes(encoded(manifest))
            actual=render(h2/BINARY,output/f'runtime-draw-{mode}',width,height,textures={0:texture,1:lut},
                          constants=constants,runtime_package=package)[0,0]
            assert np.isfinite(actual).all()
            assert np.allclose(actual,expected,atol=2e-5,rtol=3e-6), 'Runtime IniParams output mismatch'
            results.append({'initial_x7':mode,'max_error_vs_warp':float(np.max(np.abs(actual-expected)))})
        report['official_1_3_16_runtime_startup_checks']=results
        report['runtime_note']='Separate child processes verify real IniParams initialization; no key presses synthesized'
    (output/'report.json').write_bytes(encoded(report)); print(encoded(report).decode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','h1','h2','output'): p.add_argument(name,type=Path)
    p.add_argument('--runtime-check',action='store_true')
    a=p.parse_args(); validate(a.base,a.h1,a.h2,a.output,a.runtime_check)
