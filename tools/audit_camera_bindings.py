"""Read-only binding evidence for material-light projection; never authorizes a patch."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from audit_light_capture import log_blocks
from manage_preview import ROOT, digest, encoded
from patch_material_light import load_original
from shader_compile import Compiler

TARGETS = {'415a922293923fa4': 1, '980154264a89fba1': 3}
RELATED = {'e9f57e0834b642f5', '8b384acd7a03c836'}


def audit(raw):
    shaders = {}; buffers = {'PS': {}, 'VS': {}}; srvs = {}; viewport = None
    writes = {}; epoch = 0; draws = []; gaps = []
    for number, lines in log_blocks(raw):
        first = lines[0]; match = re.match(r'^(\d+) (\w+)\(', first)
        index, call = int(match[1]), match[2]
        if call in ('ClearState', 'ExecuteCommandList', 'SwapDeviceContextState'):
            shaders = {}; buffers = {'PS': {}, 'VS': {}}; srvs = {}; viewport = None
            if call != 'ClearState': epoch += 1; writes = {}
            gaps.append(dict(line=number, call=call))
        elif call in ('VSSetShader', 'PSSetShader'):
            found = re.search(r'\bhash=([0-9a-fA-F]{16})\b', first)
            shaders[call[:2]] = found[1].lower() if found else None
        elif call in ('VSSetConstantBuffers', 'PSSetConstantBuffers', 'PSSetShaderResources'):
            state = srvs if call.endswith('Resources') else buffers[call[:2]]
            start, count = map(int, re.search(r'StartSlot:(\d+), Num(?:Buffers|Views):(\d+)', first).groups())
            for slot in range(start, start + count): state.pop(slot, None)
            for line in lines[1:]:
                found = re.match(r'\s+(\d+):.*resource=(0x[0-9a-fA-F]+)', line)
                if found and start <= int(found[1]) < start + count and int(found[2], 16):
                    state[int(found[1])] = dict(resource=found[2].lower(), binding_line=number)
        elif call in ('VSSetConstantBuffers1', 'PSSetConstantBuffers1'):
            # Buffer range offsets/counts are not decoded by this audit.
            buffers[call[:2]] = {}
            gaps.append(dict(line=number, call=call, reason='ranged binding not decoded'))
        elif call == 'RSSetViewports':
            viewport = dict(line=number, call=first, numeric_values_verified=False)
        elif call in ('OMSetRenderTargets', 'OMSetRenderTargetsAndUnorderedAccessViews'):
            # Account conservatively for SRV/output binding hazards.
            outputs = {m[1].lower() for line in lines[1:] if (m := re.search(r'resource=(0x[0-9a-fA-F]+)', line))}
            srvs = {slot: value for slot, value in srvs.items() if value['resource'] not in outputs}
            if call.endswith('UnorderedAccessViews'):
                srvs = {}; gaps.append(dict(line=number, call=call, reason='UAV hazards not decoded'))
        elif call in ('Map', 'Unmap', 'UpdateSubresource', 'UpdateSubresource1', 'CopyResource',
                      'CopySubresourceRegion', 'CopySubresourceRegion1', 'ResolveSubresource'):
            resource = re.search(r'p(?:Resource|DstResource)[:=](0x[0-9a-fA-F]+)', first)
            if resource:
                key = resource[1].lower()
                writes[key] = dict(line=number, call=call, possible_content_change=True)
            else:
                epoch += 1; writes = {}
                gaps.append(dict(line=number, call=call, reason='write destination not decoded'))
        elif call.startswith(('Dispatch', 'Execute')):
            epoch += 1; writes = {}
            gaps.append(dict(line=number, call=call, reason='unmodeled GPU writes'))
        elif call.startswith('Draw') and shaders.get('PS') in TARGETS.keys() | RELATED:
            def snapshot(state):
                return {slot: dict(value, content_epoch=epoch, last_possible_write=writes.get(value['resource']))
                        for slot, value in state.items()}
            draws.append(dict(draw=index, line=number, shaders=dict(shaders),
                buffers={stage: snapshot(state) for stage, state in buffers.items()},
                srvs=snapshot(srvs), viewport=viewport))
    return dict(draws=draws, gaps=gaps)


def run(log, extraction, output):
    output.mkdir(parents=True, exist_ok=False)
    raw = log.read_bytes(); result = audit(raw)
    compiler = Compiler(ROOT/'d3dcompiler_46.dll'); metadata = {}
    for row in result['draws']:
        for stage, shader in row['shaders'].items():
            key = stage + ':' + shader
            if key in metadata: continue
            binary = load_original(extraction, shader, stage.lower() + '_5_0')
            asm = compiler.disassemble(binary)
            (output/(key.replace(':', '-') + '.asm')).write_text(asm)
            body = '\n'.join(line for line in asm.splitlines() if not line.startswith(('//', 'dcl_')))
            sizes = {int(a): int(b) for a, b in re.findall(r'dcl_constantbuffer cb(\d+)\[(\d+)\]', asm)}
            reads = {slot: sorted({int(i) for i in re.findall(r'\bcb' + str(slot) + r'\[(\d+)\]', body)}) for slot in sizes}
            metadata[key] = dict(sha256=digest(binary), declared_vectors=sizes, static_read_rows=reads,
                actual_buffer_size_verified=False, actual_read_values_verified=False)
    targets = []
    for row in result['draws']:
        ps = row['shaders']['PS']
        if ps not in TARGETS: continue
        camera = row['buffers']['PS'].get(TARGETS[ps]); peers = []
        if camera:
            for peer in result['draws']:
                for stage, slots in peer['buffers'].items():
                    shader = peer['shaders'].get(stage)
                    if not shader: continue
                    for slot, buffer in slots.items():
                        reads = metadata[stage+':'+shader]['static_read_rows'].get(slot, [])
                        if buffer['resource'] == camera['resource'] and reads and max(reads) >= 21:
                            peers.append(dict(draw=peer['draw'], stage=stage, shader=shader, slot=slot,
                                maximum_static_row=max(reads),
                                same_observed_content_epoch=buffer['content_epoch'] == camera['content_epoch'] and
                                    buffer['last_possible_write'] == camera['last_possible_write']))
        targets.append(dict(draw=row['draw'], shader=ps, camera=camera, high_row_consumers=peers,
                            viewport=row['viewport'], srvs=row['srvs']))
    files = list(log.parent.rglob('*'))
    extensions = dict(Counter(p.suffix.lower() or '<none>' for p in files if p.is_file()))
    result.update(source=str(log.resolve()), source_sha256=digest(raw), shader_metadata=metadata,
        targets=targets, capture_file_extensions=extensions, game_projection_verified=False,
        eligible_for_game_occlusion=False,
        missing_evidence=['Camera buffer bytes and allocation size at each target draw',
            'Numeric viewport and texture dimensions, including sub-rect/jitter conventions',
            'View-position/depth and normal contents in lossless floating-point resources',
            'Projection round-trip against captured positions and pixel coordinates'],
        limits=['Same pointer and observed write epoch do not prove data values, allocation size, or absence of unlogged writes',
            'Static shader reads do not prove a branch executed',
            'Only PS/VS bindings and selected passes are audited; capture is historical',
            'Resource hashes are not interpreted as buffer dimensions or contents'])
    (output/'report.json').write_bytes(encoded(result))
    print(json.dumps(dict(target_draws=len(targets), linked_high_row_consumers=sum(bool(t['high_row_consumers']) for t in targets),
        capture_file_extensions=extensions, eligible_for_game_occlusion=False), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--extraction', type=Path, default=ROOT/'artifacts/client-2026.09.15')
    a = p.parse_args(); run(a.log, a.extraction, a.output)
