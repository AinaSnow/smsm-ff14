"""Prepare a pinned official Stagehand package and perform read-only PE signature checks."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import stat
import struct
import zipfile

RELEASE='0.5.5'
ARCHIVE_SHA='6acfb640ab92a3bdcf1769fd626db4c8e6a1484c6e52eeb3536b3bb8c2589a60'
REPO_SHA='3bfc588750a7abfcb2422d54390c36de07ee6244f018c004f6dcb216ed0769ca'
LIGHT_CREATE='48 89 5C 24 ?? 57 48 83 EC 20 49 8B D8 8B F9'


def code_sections(raw):
    pe=struct.unpack_from('<I',raw,0x3c)[0]
    if raw[:2]!=b'MZ' or raw[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid client PE')
    machine,count=struct.unpack_from('<HH',raw,pe+4)
    if machine!=0x8664:raise ValueError('Expected x64 client')
    optional=struct.unpack_from('<H',raw,pe+20)[0];start=pe+24+optional
    result=[]
    for i in range(count):
        section=start+i*40;size,offset=struct.unpack_from('<II',raw,section+16);flags=struct.unpack_from('<I',raw,section+36)[0]
        if flags&0x20000000:
            if offset+size>len(raw):raise ValueError('PE section outside file')
            result.append(raw[offset:offset+size])
    if not result:raise ValueError('No executable sections')
    return result


def scan(sections,signature):
    tokens=signature.split()
    if not tokens or any(t!='??' and not re.fullmatch('[0-9A-Fa-f]{2}',t) for t in tokens):raise ValueError('Invalid signature')
    pattern=b''.join(b'.' if t=='??' else re.escape(bytes([int(t,16)])) for t in tokens)
    return sum(len(list(re.finditer(pattern,s,re.DOTALL))) for s in sections)


def prepare(archive,repo,source,game,output):
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA or hashlib.sha256(repo.read_bytes()).hexdigest()!=REPO_SHA:
        raise ValueError('Official release asset digest mismatch')
    output.mkdir(parents=True,exist_ok=False)
    package=output/'package';package.mkdir()
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>64*1024*1024:raise ValueError('Unexpected archive size')
        for item in z.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename or stat.S_ISLNK(item.external_attr>>16):
                raise ValueError('Unsafe archive member')
            if name.suffix.lower() not in ('.dll','.json','.xml'):raise ValueError('Unexpected archive member')
            path=package/item.filename
            if not path.resolve().is_relative_to(package.resolve()):raise ValueError('Archive escapes package')
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as f:f.write(z.read(item))
    manifest=json.loads((package/'Stagehand.json').read_bytes())
    if manifest['AssemblyVersion']!='0.5.5.0' or manifest['DalamudApiLevel']!=15:raise ValueError('Release identity/API mismatch')
    deps=json.loads((package/'Stagehand.deps.json').read_bytes())
    if deps['runtimeTarget']['name']!='.NETCoreApp,Version=v10.0':raise ValueError('Unexpected plugin runtime')
    version=(game/'ffxivgame.ver').read_text().strip()
    sections=code_sections((game/'ffxiv_dx11.exe').read_bytes())
    signatures=[{'name':'FFXIVClientStructs.Scene.Light.Create','signature':LIGHT_CREATE}]
    for file in sorted((source/'Stagehand').rglob('*.cs')):
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if line.startswith('//'):continue
            for value in re.findall(r'(?:Signature\(|HookFromSignature<[^>]+>\()"([0-9A-F? ]+)"',line):
                signatures.append({'name':file.relative_to(source).as_posix(),'signature':value})
    for item in signatures:item['executable_section_matches']=scan(sections,item['signature'])
    report={'schema':1,'stagehand_release':RELEASE,'archive_sha256':ARCHIVE_SHA,'repo_sha256':REPO_SHA,
            'client_build':version,'plugin_api_level':15,'plugin_runtime':'net10.0','signatures':signatures,
            'all_scanned_signatures_unique':all(s['executable_section_matches']==1 for s in signatures),
            'package_files':{p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file()},
            'game_written':False,'plugin_loaded':False,'native_light_created':False,
            'limits':['File signatures and manifest compatibility do not verify live struct resolution or rendering.','M1 must use official Stagehand native light UI/file format; no new IPC or GPU bridge.']}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('stagehand_release','client_build','all_scanned_signatures_unique','signatures')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','repo','source','game','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.archive,a.repo,a.source,a.game,a.output)
