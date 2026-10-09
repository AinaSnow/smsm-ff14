"""Submit one manual M2 command to an already loaded bridge; never queue for startup."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import uuid


def request(directory,action):
    if os.name!='nt' or action not in ('run','lifecycle','stop','status'):raise ValueError('Unsupported command/platform')
    directory=directory.resolve(strict=True)
    if directory.is_symlink() or directory.stat().st_file_attributes&0x400:raise ValueError('Expected a real bridge directory')
    status=json.loads((directory/'status.json').read_bytes())
    if status.get('pluginDisabled') is not False:raise ValueError('Bridge must already be loaded')
    pid=status['processId']
    if type(pid) is not int or pid<=0:raise ValueError('Invalid bridge process ID')
    result=subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],capture_output=True,text=True,check=True)
    rows=list(csv.reader(io.StringIO(result.stdout)))
    if not any(len(row)>=2 and row[0].lower()=='ffxiv_dx11.exe' and row[1]==str(pid) for row in rows):
        raise ValueError('Bridge status belongs to an exited game session')
    destination=directory/'command.txt';temporary=directory/('.command-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:stream.write((action+'\n').encode('ascii'));stream.flush();os.fsync(stream.fileno())
        os.rename(temporary,destination)
    finally:
        if temporary.exists():temporary.unlink()
    print('Submitted '+action+' to loaded M2 bridge')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('action',choices=['run','lifecycle','stop','status'])
    a=p.parse_args();request(a.directory,a.action)
