# -*- coding: utf-8 -*-
"""ArknightsModStudio · Windows 语音包替换 自动化测试

覆盖 PD 热更层多 Clip 语音包的完整生命周期（默认沙盒模式，不改动真实游戏）：

  T1 包结构解析（clip 列举 / 区间无重叠）
  T2 中间 Clip 替换（变长 → 后续偏移整体修正、其余 Clip 数据逐字节保留、清单语义）
  T3 提取回读（替换出的 PCM 与源音频逐字节一致）
  T4 Mod 上重复替换（官方备份不被覆盖）
  T5 首 Clip（offset=0）替换（单声道）
  T6 末 Clip 替换（无后续偏移修正）
  T7 模拟游戏更新覆盖 → reapply 一键重应用
  T8 还原 → 文件与全部清单逐字节/逐字段恢复官方值

用法：
  python test_windows_voice.py --game "F:\\...\\Arknights Game"           # 沙盒模式（推荐）
  python test_windows_voice.py --game "F:\\...\\Arknights Game" --live    # 直接测真实客户端（结束自动还原）
  python test_windows_voice.py --game ... --target audio/sound_beta_2/voice/char_002_amiya.ab
"""
import os
import sys
import json
import wave
import math
import shutil
import struct
import hashlib
import argparse
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amslib

DEFAULT_TARGET = 'audio/sound_beta_2/voice/char_002_amiya.ab'

RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond)))
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + ((' | ' + str(detail)) if detail else ''))
    return bool(cond)


def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def make_tone(path, seconds, channels=2, freq_hz=440):
    """生成 44.1kHz/16bit 正弦波测试音"""
    n = int(44100 * seconds)
    frames = bytearray()
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * freq_hz * i / 44100))
        frames += struct.pack('<h', v) * channels
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(frames))
    return path


def read_wav_pcm(path):
    with wave.open(path, 'rb') as w:
        return w.readframes(w.getnframes()), w.getnchannels()


def manifest_snapshot(game, relpath):
    """{清单路径: 条目dict} 快照（含该条目的清单才有键）"""
    snap = {}
    for lst in game['lists']:
        j = json.load(open(lst['path'], encoding='utf-8'))
        for it in j.get('abInfos', []):
            if it.get('name') == relpath:
                snap[lst['path']] = dict(it)
    return snap


def clips_by_offset(fp):
    return sorted(amslib.list_audio_clips(fp), key=lambda c: c['offset'])


def check_no_overlap(clips):
    for a, b in zip(clips, clips[1:]):
        if a['offset'] + a['size'] > b['offset']:
            return False
    return True


def others_data_preserved(backup_fp, current_fp, exclude):
    """未被替换过的 Clip 资源字节在替换前后逐一相等（exclude=已被替换的 clip 名集合）"""
    _, _, _, res_old = amslib._bundle_parts(backup_fp)
    _, _, _, res_new = amslib._bundle_parts(current_fp)
    old_clips = {c['name']: c for c in amslib.list_audio_clips(backup_fp)}
    new_clips = {c['name']: c for c in amslib.list_audio_clips(current_fp)}
    for name, oc in old_clips.items():
        if name in exclude:
            continue
        nc = new_clips.get(name)
        if nc is None or nc['size'] != oc['size']:
            return False
        if res_old[oc['offset']:oc['offset'] + oc['size']] != res_new[nc['offset']:nc['offset'] + nc['size']]:
            return False
    return True


def manifest_semantics_ok(game, relpath, snap_before, size, md5):
    """md5/abSize 同步为新值；totalSize/pid/cid/hash/type 等其余字段一律不动"""
    snap = manifest_snapshot(game, relpath)
    if set(snap) != set(snap_before):
        return False
    for lp, ent in snap.items():
        old = snap_before[lp]
        if ent.get('md5') != md5 or ent.get('abSize') != size:
            return False
        for k in old:
            if k in ('md5', 'abSize'):
                continue
            if ent.get(k) != old[k]:
                return False
    return True


def build_sandbox(real_game_dir, relpath, log):
    """复制真实清单 + 目标语音包到临时目录, 构造与真实客户端一致的双层布局"""
    sb = tempfile.mkdtemp(prefix='ams_test_')
    src = amslib.resolve_game(real_game_dir)
    sa_rel = os.path.join('Arknights_Data', 'StreamingAssets', 'AB', 'Windows')
    pd_rel = os.path.join('Arknights_Data', 'PersistentData', 'Bundles')
    # 清单原样复制（保留真实条目与字段语义）
    for lst in src['lists']:
        rel = sa_rel if 'StreamingAssets' in lst['path'] else pd_rel
        dst = os.path.join(sb, rel, os.path.basename(lst['path']))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(lst['path'], dst)
    # 目标语音包复制到其真实所在层
    src_fp = amslib.game_file(src, relpath)
    if not os.path.isfile(src_fp):
        raise RuntimeError('真实客户端中未找到目标资源: %s' % relpath)
    rel = pd_rel if src_fp.startswith(src['roots'][0]) else sa_rel
    dst_fp = os.path.join(sb, rel, *relpath.split('/'))
    os.makedirs(os.path.dirname(dst_fp), exist_ok=True)
    shutil.copy2(src_fp, dst_fp)
    log('沙盒: %s (目标在 %s 层)' % (sb, 'PD 热更' if rel == pd_rel else 'SA 基础'))
    return sb


def main():
    ap = argparse.ArgumentParser(description='Windows 语音包替换 自动化测试')
    ap.add_argument('--game', required=True, help='明日方舟 PC 客户端根目录')
    ap.add_argument('--target', default=DEFAULT_TARGET, help='目标语音包 (清单路径)')
    ap.add_argument('--live', action='store_true', help='直接操作真实游戏目录 (默认沙盒)')
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix='ams_tone_')
    sb = None
    game_dir = a.game
    try:
        tone_stereo = make_tone(os.path.join(tmp, 'stereo_2s.wav'), 2.0, channels=2)
        tone_mono = make_tone(os.path.join(tmp, 'mono_08s.wav'), 0.8, channels=1, freq_hz=550)
        if not a.live:
            sb = build_sandbox(a.game, a.target, log=lambda m: print(m))
            game_dir = sb

        game = amslib.resolve_game(game_dir)
        fp = amslib.game_file(game, a.target)
        official_md5 = md5_file(fp)
        snap0 = manifest_snapshot(game, a.target)
        print('目标: %s\n路径: %s\n官方 md5: %s (登记于 %d 份清单)'
              % (a.target, fp, official_md5, len(snap0)))

        # ---------- T1 包结构解析 ----------
        print('\n== T1 包结构解析 ==')
        clips0 = clips_by_offset(fp)
        check('clip 数量 >= 3 (实测 %d)' % len(clips0), len(clips0) >= 3)
        check('clip 区间互不重叠', check_no_overlap(clips0))
        check('clip 元数据完整 (name/length/fmt/offset/size)',
              all(c['name'] and c['size'] > 0 and c['fmt'] in amslib.FMT_NAMES for c in clips0))
        check('浏览能发现目标包', any(r[1] == a.target for r in amslib.browse_audio(game_dir)))
        first, mid, last = clips0[0], clips0[len(clips0) // 2], clips0[-1]

        # ---------- T2 中间 Clip 替换 ----------
        print('\n== T2 中间 Clip「%s」替换 (立体声 2.0s) ==' % mid['name'])
        ent = amslib.apply_mod(game_dir, tone_stereo, relpath=a.target, clip=mid['name'], log=lambda m: None)
        new_size = os.path.getsize(fp)
        new_md5 = md5_file(fp)
        check('清单字段语义 (md5/abSize 同步, 其余不动)',
              manifest_semantics_ok(game, a.target, snap0, new_size, new_md5))
        clips1 = clips_by_offset(fp)
        check('替换后可重新解析, clip 数不变', len(clips1) == len(clips0))
        t = next(c for c in clips1 if c['name'] == mid['name'])
        src_pcm, _ = read_wav_pcm(tone_stereo)
        check('目标 clip 元数据: PCM/立体声/44.1kHz/2.0s',
              t['fmt'] == 0 and t['channels'] == 2 and t['freq'] == 44100 and abs(t['length'] - 2.0) < 0.01)
        check('目标 clip 资源大小 = FSB5(68B头+PCM)', t['size'] == 68 + len(src_pcm))
        delta = t['size'] - mid['size']
        shifted = all(
            next(c for c in clips1 if c['name'] == o['name'])['offset'] == o['offset'] + delta
            for o in clips0 if o['offset'] > mid['offset'])
        check('目标之后的 clip 偏移整体 %+d' % delta, shifted)
        untouched = all(
            next(c for c in clips1 if c['name'] == o['name'])['offset'] == o['offset']
            for o in clips0 if o['offset'] < mid['offset'])
        check('目标之前的 clip 偏移不变', untouched)
        check('其余 clip 资源数据逐字节保留', others_data_preserved(amslib.backup_path(a.target), fp, {mid['name']}))
        check('状态 = active', amslib.mod_status(game_dir, a.target) == 'active')

        # ---------- T3 提取回读 ----------
        print('\n== T3 提取回读逐字节比对 ==')
        out_wav = os.path.join(tmp, 'roundtrip.wav')
        amslib.extract_clip(game_dir, a.target, mid['name'], out_wav, log=lambda m: None)
        got_pcm, got_ch = read_wav_pcm(out_wav)
        check('提取 PCM 与源音频逐字节一致', got_pcm == src_pcm and got_ch == 2)

        # ---------- T4 Mod 上重复替换 ----------
        print('\n== T4 Mod 上重复替换 (备份不覆盖) ==')
        bp = amslib.backup_path(a.target)
        backup_md5_before = md5_file(bp)
        ent2 = amslib.apply_mod(game_dir, tone_mono, relpath=a.target, clip=mid['name'], log=lambda m: None)
        check('官方备份未被覆盖', md5_file(bp) == backup_md5_before)
        check('official_md5 保持官方值', ent2['official_md5'] == official_md5)
        check('mod_md5 已更新', ent2['mod_md5'] == md5_file(fp) and ent2['mod_md5'] != ent['mod_md5'])

        # ---------- T5 首 Clip 替换 ----------
        print('\n== T5 首 Clip「%s」(offset=0) 替换 ==' % first['name'])
        amslib.apply_mod(game_dir, tone_mono, relpath=a.target, clip=first['name'], log=lambda m: None)
        clips2 = clips_by_offset(fp)
        t5 = next(c for c in clips2 if c['name'] == first['name'])
        check('首 clip offset 保持 0, 单声道元数据正确',
              t5['offset'] == 0 and t5['channels'] == 1 and t5['fmt'] == 0)
        check('区间无重叠', check_no_overlap(clips2))
        check('其余 clip 数据保留', others_data_preserved(amslib.backup_path(a.target), fp, {mid['name'], first['name']}))

        # ---------- T6 末 Clip 替换 ----------
        print('\n== T6 末 Clip「%s」替换 ==' % last['name'])
        amslib.apply_mod(game_dir, tone_stereo, relpath=a.target, clip=last['name'], log=lambda m: None)
        clips3 = clips_by_offset(fp)
        check('末 clip 替换后区间无重叠', check_no_overlap(clips3))
        check('其余 clip 数据保留', others_data_preserved(amslib.backup_path(a.target), fp, {mid['name'], first['name'], last['name']}))
        check('清单仍同步', manifest_semantics_ok(game, a.target, snap0, os.path.getsize(fp), md5_file(fp)))

        # ---------- T7 模拟更新覆盖 + reapply ----------
        print('\n== T7 模拟游戏更新覆盖 -> reapply ==')
        shutil.copy2(amslib.backup_path(a.target), fp)   # 静默恢复官方文件, 模拟更新覆盖
        check('状态 = overwritten', amslib.mod_status(game_dir, a.target) == 'overwritten')
        amslib.reapply_all(game_dir, log=lambda m: None)
        check('reapply 后状态 = active', amslib.mod_status(game_dir, a.target) == 'active')
        check('清单仍同步', manifest_semantics_ok(game, a.target, snap0, os.path.getsize(fp), md5_file(fp)))

        # ---------- T8 还原 ----------
        print('\n== T8 还原官方原版 ==')
        amslib.restore_mod(game_dir, a.target, log=lambda m: None)
        check('文件 md5 恢复官方值', md5_file(fp) == official_md5)
        check('全部清单逐字段恢复', manifest_snapshot(game, a.target) == snap0)
        check('状态 = official', amslib.mod_status(game_dir, a.target) == 'official')

    finally:
        # 兜底: live 模式下若测试中断且仍有 mod 生效, 尽量还原
        if a.live:
            try:
                if amslib.mod_status(game_dir, a.target) in ('active', 'overwritten'):
                    amslib.restore_mod(game_dir, a.target, log=lambda m: None)
                    print('[cleanup] 已兜底还原 %s' % a.target)
            except Exception as e:
                print('[cleanup] 兜底还原失败: %s' % e)
        shutil.rmtree(tmp, ignore_errors=True)
        if sb:
            shutil.rmtree(sb, ignore_errors=True)

    print('\n================ 结果 ================')
    n_pass = sum(1 for _, ok in RESULTS if ok)
    for name, ok in RESULTS:
        if not ok:
            print('  FAIL: ' + name)
    print('通过 %d / %d' % (n_pass, len(RESULTS)))
    sys.exit(0 if n_pass == len(RESULTS) else 1)


if __name__ == '__main__':
    main()
