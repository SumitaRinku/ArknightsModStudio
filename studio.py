# -*- coding: utf-8 -*-
"""ArknightsModStudio CLI (Windows PC / macOS PlayCover)

明日方舟音频 Mod 工作台: 通用音频替换 / 浏览提取 / Mod 管理 / 一键重应用
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amslib


def _saved_game_dir():
    return amslib.load_config().get('game_dir', '')


def cmd_status(game):
    st = amslib.studio_status(game)
    g = st['game']
    print('游戏目录 : %s (%s)' % (g['base'], 'Windows PC' if g['platform'] == 'win' else 'macOS PlayCover'))
    print('清单版本 : %s' % st['manifest_version'])
    mods = st['mods']
    if not mods:
        print('已装 Mod : 无')
    else:
        print('已装 Mod : %d 个' % len(mods))
        for m in mods:
            print('  %s  %s' % (amslib.STATUS_TEXT[m['status']], m['relpath']))
            print('           clip=%s  应用时间=%s' % (m['clip'], m['applied_at']))
    if st['counts'].get('overwritten'):
        print('\n提示: 有 %d 个 Mod 被游戏更新覆盖, 运行 --reapply 可一键重新应用' % st['counts']['overwritten'])


def cmd_browse(game, keyword):
    rows = amslib.browse_audio(game, keyword)
    if not rows:
        if keyword:
            print('没有匹配的音频资源 (关键词: %s)' % keyword)
        else:
            print('没有找到音频资源')
        return
    cur_cat = None
    for cat, relpath, size in rows:
        if cat != cur_cat:
            print('\n== %s ==' % cat)
            cur_cat = cat
        print('  %-70s %8.1f KB' % (relpath, size / 1024))
    print('\n共 %d 个资源包。替换: --apply <音频> --target <上面的路径> [--clip <名>]' % len(rows))


def cmd_apply(game, audio, target, clip):
    print('替换为: %s' % audio)
    print('目标:   %s%s' % (target, ('  clip=' + clip) if clip else ''))
    info = amslib.apply_mod(game, audio, relpath=target, clip=clip)
    print('完成! 启动游戏即可生效。')


def cmd_extract(game, target, clip, out, vgm):
    clips = amslib.list_audio_clips(amslib._require_ab(amslib.resolve_game(game), target))
    if not clip:
        if len(clips) == 1:
            clip = clips[0]['name']
        else:
            print('该 bundle 含 %d 个 clip, 请用 --clip 指定:' % len(clips))
            for c in clips:
                print('  %-40s %6.1fs  %s' % (c['name'], c['length'],
                                              amslib.FMT_NAMES.get(c['fmt'], c['fmt'])))
            return
    if not out:
        base = os.path.splitext(os.path.basename(clip))[0]
        out = os.path.join(os.path.expanduser('~/Downloads'), base + '.wav')
    amslib.extract_clip(game, target, clip, out, vgmstream=vgm)


def cmd_mods(game):
    mods = amslib.list_mods(game)
    if not mods:
        print('注册表为空 (尚未安装任何 Mod)')
        return
    for m in mods:
        print('%s  %s' % (amslib.STATUS_TEXT[m['status']], m['relpath']))
        print('        clip=%s  应用时间=%s  源音频=%s' % (m['clip'], m['applied_at'], m['source'] or '(未知)'))


def main():
    ap = argparse.ArgumentParser(
        description='ArknightsModStudio - 明日方舟音频 Mod 工作台 (Windows PC / macOS PlayCover)')
    ap.add_argument('--game', help='游戏目录: Windows 传 PC 客户端根目录(含 Arknights_Data); '
                                   'macOS 传 PlayCover 的 .../Data/Documents/Bundles 目录, 留空自动检测')
    ap.add_argument('--vgmstream', help='vgmstream-cli 路径 (Vorbis 提取/试听需要)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--status', action='store_true', help='现状总览')
    g.add_argument('--browse', nargs='?', const='', metavar='关键词', help='浏览可替换的音频资源 (可按关键词过滤)')
    g.add_argument('--apply', metavar='音频', help='替换音频 (wav/mp3/flac/m4a, 自动转换)')
    g.add_argument('--extract', metavar='资源路径', help='导出 clip 为 WAV')
    g.add_argument('--mods', action='store_true', help='查看 Mod 注册表与状态')
    g.add_argument('--restore', metavar='资源路径', help='还原指定 Mod 为官方原版')
    g.add_argument('--restore-all', action='store_true', help='还原全部 Mod')
    g.add_argument('--reapply', action='store_true', help='重新应用被游戏更新覆盖的 Mod')
    ap.add_argument('--target', default=amslib.DEFAULT_ENTRY,
                    help='目标资源 (清单内 audio/**.ab 路径, 默认: 扬升主题主界面 BGM)')
    ap.add_argument('--clip', help='目标 AudioClip 名 (多 clip 资源如语音包必填)')
    ap.add_argument('--out', help='导出 WAV 输出路径 (默认 ~/Downloads)')
    a = ap.parse_args()

    amslib.migrate_legacy()                  # 旧版单文件备份自动迁移
    game = a.game or _saved_game_dir()
    vgm = a.vgmstream or amslib.find_vgmstream(amslib.load_config())

    if a.status:
        cmd_status(game)
    elif a.browse is not None:
        cmd_browse(game, a.browse or None)
    elif a.apply:
        cmd_apply(game, a.apply, a.target, a.clip)
    elif a.extract:
        cmd_extract(game, a.extract, a.clip, a.out, vgm)
    elif a.mods:
        cmd_mods(game)
    elif a.restore:
        amslib.restore_mod(game, a.restore)
    elif a.restore_all:
        amslib.restore_all(game)
    elif a.reapply:
        amslib.reapply_all(game)


if __name__ == '__main__':
    main()
