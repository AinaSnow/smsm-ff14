"""One-step SMSM install, uninstall, rollback and status for the release ZIP (double-click the .cmd files).

Finds the game folder, checks the game is closed and the client version, turns off Dalamud's external
windows when needed (with a backup), keeps a private copy of the package under %LOCALAPPDATA%\\SMSM so
the extracted ZIP can be deleted, and installs the default effects through manage_preview's transactions.
"""
import argparse
import json
import os
import re
import shutil
import sys
import winreg
from datetime import datetime, timezone
from pathlib import Path
import manage_preview as m
from configure_compat_viewports import configure

ZIP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SE = Path(r'C:\Program Files (x86)\SquareEnix\FINAL FANTASY XIV - A Realm Reborn')


def home():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'SMSM'


def appdata():
    return Path(os.environ.get('APPDATA', Path.home()/'AppData/Roaming'))


def is_client(root):
    return root is not None and (Path(root)/'game/ffxivgame.ver').is_file()


def steam_libraries():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            steam = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    except OSError:
        return []
    vdf = steam/'steamapps/libraryfolders.vdf'
    paths = [steam]
    if vdf.is_file():
        paths += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding='utf-8', errors='ignore'))]
    return paths


def find_client(explicit=None):
    """Explicit path, XIVLauncher's GamePath, Steam libraries, then the Square Enix default."""
    if explicit:
        # A path the user named is used or rejected, never silently replaced by an auto-detected one.
        if is_client(explicit):
            return Path(explicit).resolve()
        raise SystemExit(f'找不到游戏：{explicit} 下没有 game\\ffxivgame.ver。请指定含 game 文件夹的游戏根目录。')
    candidates = []
    config = appdata()/'XIVLauncher/launcherConfigV3.json'
    if config.is_file():
        try:
            candidates.append(Path(json.loads(config.read_text(encoding='utf-8-sig'))['GamePath']))
        except (KeyError, ValueError, TypeError):
            pass
    candidates += [lib/'steamapps/common/FINAL FANTASY XIV Online' for lib in steam_libraries()]
    candidates.append(DEFAULT_SE)
    for candidate in candidates:
        if is_client(candidate):
            return candidate.resolve()
    raise SystemExit('没有自动找到游戏目录。请用 --client-root 指定含 game 文件夹的游戏根目录。')


def stored_package(source, root):
    """Copy the ZIP's package into %LOCALAPPDATA%\\SMSM\\packages\\<digest> once; reuse if identical."""
    manifest, receipt = m.read_package(source)
    target = root/'packages'/m.digest(receipt)[:16]
    if target.exists():
        m.read_package(target)
        return target
    temp = target.with_name(target.name + '.partial')
    if temp.exists():
        shutil.rmtree(temp)
    for name in list(manifest['files']) + [m.RECEIPT]:
        path = temp/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source/name).read_bytes())
    m.read_package(temp)
    temp.rename(target)
    return target


# Longest path the manager writes under the data folder (backup dir, shader file, temp suffix).
LONGEST_BACKUP = len(r'\backups\20261114T090713Z-094976d3ef7946ceac9b8434c88d05aa\files\SMSM-ShaderFixes'
                     r'\72a656dfd52149ad-ps_replace.bin.smsm-6bfec341ea54445c8998947ab34016ec')


def check_path_length(root):
    if len(str(root.resolve())) + LONGEST_BACKUP >= 259:
        raise SystemExit(f'数据目录路径过长：{root}\nWindows 默认限制路径 260 个字符，备份文件会写不进去。'
                         '请把 LOCALAPPDATA 指向较短的目录后重试。本次未做任何修改。')


def prepare(client, root=None):
    if root is not None:
        check_path_length(root)
    game = (client/'game').resolve(strict=True)
    if m.running_game(game):
        raise SystemExit('游戏正在运行，请先完全退出游戏再操作。')
    if (game/m.JOURNAL).exists():
        m.recover(game)
        print('发现上次中断的操作，已自动恢复。')
    return game


def record(root, action, client, backup, extra=None):
    root.mkdir(parents=True, exist_ok=True)
    data = {'time_utc': datetime.now(timezone.utc).isoformat(), 'action': action, 'client_root': str(client),
            'backup': str(backup)}
    data.update(extra or {})
    m.write_atomic(root/'last-operation.json', m.encoded(data))


def ensure_dalamud(game, root):
    config = appdata()/'XIVLauncher/dalamudConfig.json'
    if not config.is_file():
        print('未发现 Dalamud 配置（未使用 XIVLauncher），跳过窗口设置。')
        return None
    if json.loads(config.read_text(encoding='utf-8-sig')).get('IsDisableViewport') is True:
        print('Dalamud 外部窗口已关闭，无需修改。')
        return None
    backup = root/'dalamud-backups'/datetime.now().strftime('%Y%m%d-%H%M%S')
    configure(config, backup, game)
    print(f'已关闭 Dalamud 外部窗口（IsDisableViewport=true），原配置备份在 {backup}')
    return backup


def install(client, package_dir, root, profile='daily'):
    game = prepare(client, root)
    manifest, _ = m.read_package(package_dir)
    version = (game/'ffxivgame.ver').read_text().strip()
    if version != manifest['client_build']:
        # No version gate: 3DMigoto replaces by shader content hash, so a shader the update changed is
        # simply not replaced and its effect turns off; nothing lands on the wrong shader.
        print(f'提示：游戏版本 {version} 与本包验证过的 {manifest["client_build"]} 不同，仍继续安装。')
        print('游戏若改动了被替换的 shader，对应效果会自动失效（不会出错），其余效果照常生效。')
    stored = stored_package(package_dir, root)
    manifest, receipt = m.read_package(stored)
    dalamud = ensure_dalamud(game, root)
    before, _, _ = m.snapshot(game)
    effects, label = m.selection(manifest, profile)
    after = m.desired_package(stored, manifest, receipt, effects, label)
    backup = m.transition(game, before, after, root/'backups')
    record(root, 'install', client, backup, {'package': str(stored), 'effects': effects,
                                            'dalamud_backup': str(dalamud) if dalamud else None})
    print(f'安装完成：{manifest["compatibility_candidate"]["id"]}，效果 {", ".join(effects) or "无"}。启动游戏即生效。')
    print(f'安装前的文件已备份到 {backup}；双击 Rollback.cmd 可恢复。')
    return backup


def uninstall(client, root):
    game = prepare(client, root)
    before, current, _ = m.snapshot(game)
    if not current:
        raise SystemExit('当前没有安装 SMSM。')
    backup = m.transition(game, before, {}, root/'backups')
    record(root, 'uninstall', client, backup)
    print(f'已卸载，游戏恢复原版文件。卸载前的状态备份在 {backup}；双击 Rollback.cmd 可重新装回。')
    print('Dalamud 外部窗口设置保持关闭；需要时在 Dalamud 设置里自行打开。')
    return backup


def rollback(client, root):
    log = root/'last-operation.json'
    if not log.is_file():
        raise SystemExit('没有可回退的记录。')
    last = json.loads(log.read_text(encoding='utf-8'))
    client = client or Path(last['client_root'])
    game = prepare(client, root)
    before, _, _ = m.snapshot(game)
    after = m.read_backup(Path(last['backup']), game)
    backup = m.transition(game, before, after, root/'backups')
    record(root, 'rollback', client, backup, {'restored_from': last['backup']})
    print(f'已恢复到上一次操作（{last["action"]}）之前的状态。当前状态备份在 {backup}，再次回退会撤销这次恢复。')
    return backup


def status(client):
    game = (client/'game').resolve(strict=True)
    _, current, state = m.snapshot(game)
    version = (game/'ffxivgame.ver').read_text().strip()
    print(f'游戏目录：{client}\n游戏版本：{version}')
    if not current:
        print('SMSM：未安装')
        return
    ok = version == current['client_build']
    print(f'SMSM：{current["compatibility_candidate"]["id"]}，效果 {", ".join(state["effects"]) or "无"}')
    print('文件完整，游戏版本与本包验证过的版本一致。' if ok else
          f'文件完整。本包在 {current["client_build"]} 上验证过，当前游戏版本未验证：'
          '效果按 shader 内容生效，游戏改动过的 shader 对应效果会自动失效。')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('install', 'uninstall', 'rollback', 'status'))
    p.add_argument('--client-root', help='含 game 文件夹的游戏根目录（默认自动查找）')
    p.add_argument('--package', type=Path, default=ZIP_ROOT/'package')
    p.add_argument('--profile', default='daily', help='daily = 全部默认效果；vanilla = 只装运行库')
    a = p.parse_args(argv)
    root = home()
    if a.action == 'rollback' and not a.client_root:
        client = None
    else:
        client = find_client(a.client_root)
    {'install': lambda: install(client, a.package, root, a.profile),
     'uninstall': lambda: uninstall(client, root),
     'rollback': lambda: rollback(client, root),
     'status': lambda: status(client)}[a.action]()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f'操作失败：{error}', file=sys.stderr)
        print('如果操作中途停止，重新运行一次会先自动恢复到操作前的文件。', file=sys.stderr)
        sys.exit(1)
