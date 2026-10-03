# -*- coding: utf-8 -*-
"""ArknightsModStudio 核心库 (Windows PC / macOS PlayCover 通用)

明日方舟音频 Mod 工作台:
- 通用音频替换: 任意清单内 audio/**.ab 的任意 AudioClip (BGM/干员语音/音效)
- 音频浏览与提取: 按目录浏览, PCM 原生导出 WAV, Vorbis 经 vgmstream 导出
- Mod 管理: mods.json 注册表, 逐个/全部还原, 更新覆盖检测与一键重应用
- 自动格式转换: mp3/flac/m4a 自动转 44.1kHz/16bit WAV (macOS afconvert / Windows ffmpeg)

不修改游戏程序本体, 只替换 AssetBundle 资源文件并同步清单 md5/abSize。
"""
import sys, os, io, json, wave, struct, shutil, hashlib, subprocess, tempfile, datetime

# UnityPy / lz4 依赖: 优先使用 pip 安装的版本; 其次找脚本旁的 pkgs 目录
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, 'pkgs'), r'C:\Users\09\.local\lib\unitypy_pkgs'):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
sys.path.insert(0, _HERE)   # 本目录优先, 避免外部同名模块遮蔽 akparse
import lz4.block
import UnityPy
from akparse import parse

# ============ 常量 ============
DEFAULT_ENTRY = 'audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab'  # 扬升主题主界面 BGM
DEFAULT_CLIP  = 'm_sys_act54side_mainpage_loop'
MAC_DEFAULT_BASE = os.path.expanduser('~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles')
IOS_LISTS = ['hot_update_list.json', 'persistent_res_list.json']

DATA_DIR    = _HERE
BACKUP_DIR  = os.path.join(_HERE, 'backup')
FILES_DIR   = os.path.join(BACKUP_DIR, 'files')     # backup/files/<清单相对路径> 官方原版
LEGACY_DIR  = os.path.join(BACKUP_DIR, 'legacy')    # 旧版平铺备份迁移后的存档
MODS_JSON   = os.path.join(_HERE, 'mods.json')
CONFIG_JSON = os.path.join(_HERE, 'config.json')

# 浏览分类 (按前缀最长匹配)
CATEGORIES = [
    ('音乐 BGM',   'audio/sound_beta_2/music/'),
    ('干员语音·中', 'audio/sound_beta_2/voice_cn/'),
    ('干员语音',   'audio/sound_beta_2/voice/'),
    ('自定义语音',  'audio/sound_beta_2/voice_custom/'),
    ('氛围/环境音', 'audio/sound_beta_2/ambience'),
    ('音效',      'audio/sound_beta_2/'),
    ('其他音频',   'audio/'),
]

FMT_NAMES = {0: 'PCM16', 1: 'Vorbis', 2: 'ADPCM', 3: 'AT9'}


# ============ 配置 ============
def load_config():
    if os.path.exists(CONFIG_JSON):
        try:
            return json.load(open(CONFIG_JSON, encoding='utf-8'))
        except Exception:
            pass
    return {}

def save_config(cfg):
    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ============ 平台 / 路径 ============
def resolve_game(base=''):
    """识别 Windows / macOS(PlayCover) 两种布局。

    返回 dict(base, platform, file_root, lists, total_eq_size):
    - Windows: base 为 PC 客户端根目录 (含 Arknights_Data), 清单 totalSize == 文件大小
    - macOS:   base 为 Bundles 热更目录; 条目可能登记在两份清单中,
               totalSize 为下载记账值 (恒 != 磁盘大小), 只同步 md5/abSize
    - macOS 下 base 留空时自动使用 PlayCover 默认容器路径
    """
    base = (base or '').rstrip('\\/')
    if not base and sys.platform == 'darwin':
        base = MAC_DEFAULT_BASE
    if base and os.path.isdir(os.path.join(base, 'Arknights_Data')):
        root = os.path.join(base, 'Arknights_Data', 'StreamingAssets', 'AB', 'Windows')
        lists = [os.path.join(root, 'hot_update_list.json')]
        total_eq_size = True
        platform = 'win'
    elif base and os.path.isfile(os.path.join(base, 'hot_update_list.json')):
        root = base
        lists = [os.path.join(base, f) for f in IOS_LISTS if os.path.isfile(os.path.join(base, f))]
        total_eq_size = False
        platform = 'ios'
    else:
        raise RuntimeError(
            '无法识别游戏目录:\n%s\n'
            'Windows: 传入 PC 客户端根目录 (含 Arknights_Data\\StreamingAssets)\n'
            'macOS:   传入 PlayCover 的 .../Data/Documents/Bundles 目录, 或留空自动检测' % (base or '(空)'))
    return dict(base=base, platform=platform, file_root=root, lists=lists, total_eq_size=total_eq_size)

def game_file(game, relpath):
    """清单条目名 -> 游戏内 .ab 绝对路径"""
    return os.path.join(game['file_root'], *relpath.split('/'))

def _require_ab(game, relpath):
    fp = game_file(game, relpath)
    if not os.path.isfile(fp):
        raise RuntimeError('未找到游戏资源文件 (可能尚未下载该资源):\n%s' % fp)
    return fp


# ============ 音频输入 (读取 / 自动转换 / FSB5 构建) ============
def read_wav(path):
    """读取 WAV, 要求 44.1kHz/16bit, 单声道或立体声。返回 (pcm, 帧数, 声道数)"""
    w = wave.open(path, 'rb')
    nch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    if (sw, sr) != (2, 44100) or nch not in (1, 2):
        w.close()
        raise ValueError('仅支持 44.1kHz / 16bit / 单声道或立体声 WAV, 当前: ch=%d width=%d rate=%d'
                         % (nch, sw, sr))
    pcm = w.readframes(nf)
    w.close()
    return pcm, nf, nch

def _convert_audio(src, tmpdir):
    """非 WAV 输入转 44.1kHz/16bit/立体声 WAV (macOS afconvert / Windows ffmpeg)"""
    out = os.path.join(tmpdir, 'conv_%d.wav' % os.getpid())
    if sys.platform == 'darwin':
        cmd = ['afconvert', '-f', 'WAVE', '-d', 'LEI16@44100', '-c', '2', src, out]
        hint = 'macOS 系统自带 afconvert, 理论上不应缺失'
    else:
        ff = shutil.which('ffmpeg')
        if not ff:
            raise RuntimeError('未找到 ffmpeg, 无法自动转换 %s\n'
                               '安装: winget install Gyan.FFmpeg 或 https://ffmpeg.org/download.html\n'
                               '或自行转换为 44.1kHz/16bit/立体声 WAV 后再使用' % os.path.basename(src))
        cmd = [ff, '-y', '-i', src, '-ar', '44100', '-ac', '2', '-sample_fmt', 's16', out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError('音频转换失败: %s\n%s' % (' '.join(cmd), r.stderr.decode('utf-8', 'ignore')[:500]))
    return out

def prepare_audio(src, log=print):
    """任意输入 (wav/mp3/flac/m4a...) -> (pcm, 帧数, 声道数)。非 WAV 自动转换。"""
    ext = os.path.splitext(src)[1].lower()
    tmp = None
    try:
        if ext == '.wav':
            wav = src
        else:
            tmp = tempfile.mkdtemp(prefix='ams_')
            wav = _convert_audio(src, tmp)
            log('已自动转换: %s -> 44.1kHz/16bit/立体声 WAV' % os.path.basename(src))
        return read_wav(wav)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

def build_fsb5_pcm16(pcm, samples, channels=2, freq_code=8):
    """FSB5 头 60 字节 + 8 字节采样头 (无 chunk) + PCM 数据, 布局与原版一致"""
    header = struct.pack('<4sIIIIII8s16s8s',
        b'FSB5', 1, 1, 8, 0, len(pcm), 2, b'\x00'*8, b'\x00'*16, b'\x00'*8)
    q = (freq_code << 1) | ((channels - 1) << 5) | (samples << 34)
    return header + struct.pack('<Q', q) + pcm


# ============ Bundle 解析 / clip 列举 / 替换 ============
def _bundle_parts(ab_path):
    """解析 bundle -> (nodes_meta, cab_bytes, resource_bytes, 头部参数)"""
    r = parse(ab_path)
    nm = r['nodes']
    if len(nm) < 2 or not nm[1]['name'].endswith('.resource'):
        raise RuntimeError('bundle 结构与预期不符 (节点数=%d), 游戏可能已更新' % len(nm))
    cab = r['data'][:nm[0]['size']]
    res = r['data'][nm[0]['size']:nm[0]['size'] + nm[1]['size']]
    return r, nm, cab, res

def list_audio_clips(ab_path):
    """列出 bundle 内全部 AudioClip: name/path_id/length/channels/freq/fmt/offset/size"""
    _, _, cab, _ = _bundle_parts(ab_path)
    env = UnityPy.load(io.BytesIO(cab))
    clips = []
    for obj in env.objects:
        if obj.type.name == 'AudioClip':
            d = obj.read()
            clips.append(dict(
                name=d.m_Name, path_id=obj.path_id,
                length=float(d.m_Length), channels=int(d.m_Channels),
                freq=int(d.m_Frequency), fmt=int(d.m_CompressionFormat),
                offset=int(d.m_Resource.m_Offset), size=int(d.m_Resource.m_Size)))
    clips.sort(key=lambda c: (c['offset'], c['name']))
    return clips

def replace_clip(ab_path, clip_name, fsb, duration, channels=2, freq=44100, log=print):
    """把 bundle 内指定 AudioClip 的资源替换为新的 FSB5, 返回新 bundle 字节。

    - 单 clip bundle: .resource 节点整体替换 (偏移归零)
    - 多 clip bundle (语音包等): 在原资源流中拼接替换, 其后 clip 偏移整体后移
    """
    r, nm, cab, res = _bundle_parts(ab_path)
    env = UnityPy.load(io.BytesIO(cab))
    target = None
    others = []
    for obj in env.objects:
        if obj.type.name != 'AudioClip':
            continue
        d = obj.read()
        if d.m_Name == clip_name:
            target = (obj, d)
        else:
            others.append((obj, d))
    if target is None:
        names = ', '.join(sorted(d.m_Name for _, d in others)) or '(无)'
        raise RuntimeError('bundle 中未找到 AudioClip: %s\n现有 clip: %s' % (clip_name, names[:400]))

    tobj, td = target
    t_off, t_size = int(td.m_Resource.m_Offset), int(td.m_Resource.m_Size)
    if len(others) == 0:
        # 单 clip: 整个 .resource 即新 FSB5
        new_res = fsb
        td.m_Resource.m_Offset = 0
    else:
        if not (0 <= t_off <= len(res)) or t_off + t_size > len(res):
            raise RuntimeError('目标 clip 资源区间异常 (off=%d size=%d, 资源总长 %d), 游戏可能已更新'
                               % (t_off, t_size, len(res)))
        new_res = res[:t_off] + fsb + res[t_off + t_size:]
        delta = len(fsb) - t_size
        for obj, d in others:
            off = int(d.m_Resource.m_Offset)
            if off >= t_off + t_size:      # 位于目标之后: 偏移后移
                d.m_Resource.m_Offset = off + delta
                d.save()
        td.m_Resource.m_Offset = t_off     # 目标自身偏移不变
        log('      多 clip 拼接: %d 条其余语音保留, 偏移修正 %+d 字节' % (len(others), delta))
    td.m_Length = float(duration)
    td.m_CompressionFormat = 0             # PCM
    td.m_Channels = channels
    td.m_Frequency = freq
    td.m_Resource.m_Size = len(fsb)
    td.save()

    new_cab = env.file.save()
    new_ab = build_bundle(
        [dict(name=nm[0]['name'], data=new_cab, status=nm[0]['status']),
         dict(name=nm[1]['name'], data=fsb if len(others) == 0 else new_res, status=nm[1]['status'])],
        version=r['version'], flags=r['flags'], ver=r['ver'], rev=r['rev'])
    return new_ab


# ============ UnityFS bundle 重打包 ============
def _align16(x):
    return (x + 15) & ~15

def build_bundle(nodes, flags=0x243, version=8, ver=b'5.x.x', rev=b'2021.3.39f1', block_size=131072):
    """按原 bundle 的头部参数 (version/flags/ver/rev) 重打包, 保持格式一致"""
    data = b''.join(n['data'] for n in nodes)
    blocks = []
    for off in range(0, len(data), block_size):
        chunk = data[off:off+block_size]
        comp = lz4.block.compress(chunk, mode='high_compression', store_size=False)
        if len(comp) < len(chunk):
            blocks.append((len(chunk), len(comp), 3, comp))
        else:
            blocks.append((len(chunk), len(chunk), 0, chunk))
    # blocksInfo: 16字节hash(全零) + 块表 + 节点表
    bi = b'\x00' * 16 + struct.pack('>i', len(blocks))
    for us, cs, fl, _ in blocks:
        bi += struct.pack('>IIH', us, cs, fl)
    bi += struct.pack('>i', len(nodes))
    off = 0
    for n in nodes:
        bi += struct.pack('>qqi', off, len(n['data']), n['status'])
        bi += n['name'].encode('utf-8') + b'\x00'
        off += len(n['data'])
    ubs = len(bi)
    cbi = lz4.block.compress(bi, mode='high_compression', store_size=False)
    head = b'UnityFS\x00' + struct.pack('>i', version) + ver + b'\x00' + rev + b'\x00'
    data_start = _align16(len(head) + 20) + len(cbi)
    if flags & 0x200:
        data_start = _align16(data_start)
    total = data_start + sum(cs for _, cs, _, _ in blocks)
    head += struct.pack('>QIIi', total, len(cbi), ubs, flags)
    out = head + b'\x00' * (_align16(len(head)) - len(head)) + cbi
    if flags & 0x200:
        out += b'\x00' * (_align16(len(out)) - len(out))
    for _, _, _, comp in blocks:
        out += comp
    assert len(out) == total
    return out


# ============ 清单 ============
def _md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def sync_manifest_entry(game, relpath, md5, size, log=None):
    """在所有含该条目的清单中同步 md5/abSize (Windows 另同步 totalSize)"""
    updated = []
    for lp in game['lists']:
        j = json.load(open(lp, encoding='utf-8'))
        hit = False
        for it in j.get('abInfos', []):
            if it.get('name') == relpath:
                it['md5'] = md5
                it['abSize'] = size
                if game['total_eq_size']:   # Windows: totalSize==文件大小; iOS: 保留下载记账值
                    it['totalSize'] = size
                hit = True
        if hit:
            with open(lp, 'w', encoding='utf-8', newline='') as f:
                f.write(json.dumps(j, separators=(',', ':'), ensure_ascii=False))
            updated.append(os.path.basename(lp))
            if log:
                log('      清单已同步: %s' % os.path.basename(lp))
    if not updated:
        raise RuntimeError('所有清单中均未找到条目: %s\n(资源可能未下载或不在热更清单内)' % relpath)
    return updated

def manifest_entries(game):
    """主清单 (hot_update_list) 全部条目名 -> (md5, abSize)"""
    lp = game['lists'][0]
    j = json.load(open(lp, encoding='utf-8'))
    return {it['name']: (it.get('md5', ''), it.get('abSize', 0)) for it in j.get('abInfos', [])}

def manifest_version(game):
    lp = game['lists'][0]
    j = json.load(open(lp, encoding='utf-8'))
    return j.get('manifestVersion', '?')


# ============ 注册表 (mods.json) ============
def load_mods():
    if os.path.exists(MODS_JSON):
        try:
            return json.load(open(MODS_JSON, encoding='utf-8')).get('mods', {})
        except Exception:
            pass
    return {}

def save_mods(mods):
    with open(MODS_JSON, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'mods': mods}, f, ensure_ascii=False, indent=2)

def backup_path(relpath):
    return os.path.join(FILES_DIR, *relpath.split('/'))

def migrate_legacy(log=print):
    """旧版平铺备份 (backup/m_sys_act54side_mainpage.ab.bak) 迁移到新布局并登记注册表"""
    old_ab = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    if not os.path.exists(old_ab):
        return False
    mods = load_mods()
    if DEFAULT_ENTRY in mods:      # 已迁移过
        return False
    os.makedirs(os.path.dirname(backup_path(DEFAULT_ENTRY)), exist_ok=True)
    shutil.move(old_ab, backup_path(DEFAULT_ENTRY))
    # 旧清单备份挪到 legacy (新方案按条目同步, 不再需要整文件还原)
    os.makedirs(LEGACY_DIR, exist_ok=True)
    for f in os.listdir(BACKUP_DIR):
        if f.endswith('.json.bak'):
            shutil.move(os.path.join(BACKUP_DIR, f), os.path.join(LEGACY_DIR, f))
    # 当前游戏文件若非官方备份, 即为旧版已替换的 mod -> 登记 mod_md5
    official_md5 = _md5_file(backup_path(DEFAULT_ENTRY))
    mod_md5 = ''
    try:
        fp = game_file(resolve_game(''), DEFAULT_ENTRY)
        if os.path.isfile(fp):
            cur = _md5_file(fp)
            if cur != official_md5:
                mod_md5 = cur
    except Exception:
        pass
    mods[DEFAULT_ENTRY] = dict(
        clip=DEFAULT_CLIP, applied_at='(迁移自旧版)',
        source_audio=None, official_md5=official_md5, mod_md5=mod_md5)
    save_mods(mods)
    log('已迁移旧版备份 -> backup/files/, 并登记到 mods.json')
    return True

def _resolve_clip(clip, clips, relpath):
    """确定替换目标 clip: 指定名 / 唯一 clip / 默认 clip"""
    if clip:
        for c in clips:
            if c['name'] == clip:
                return clip
        raise RuntimeError('bundle 中未找到 clip: %s\n现有: %s'
                           % (clip, ', '.join(c['name'] for c in clips)[:400]))
    if len(clips) == 1:
        return clips[0]['name']
    if any(c['name'] == DEFAULT_CLIP for c in clips):
        return DEFAULT_CLIP
    raise RuntimeError('%s 含 %d 个 clip, 请用 --clip 指定目标:\n%s'
                       % (relpath, len(clips), '\n'.join('  %s (%.1fs, %s)'
                           % (c['name'], c['length'], FMT_NAMES.get(c['fmt'], c['fmt'])) for c in clips)))


# ============ Mod 生命周期 ============
def apply_mod(game_dir, audio_path, relpath=DEFAULT_ENTRY, clip=None, log=print):
    """完整替换流程: 转换音频 -> 替换 clip -> 备份原版 -> 写入 -> 同步清单 -> 登记"""
    game = resolve_game(game_dir)
    fp = _require_ab(game, relpath)
    if not os.path.isfile(audio_path):
        raise RuntimeError('音频文件不存在: %s' % audio_path)

    clips = list_audio_clips(fp)
    target = _resolve_clip(clip, clips, relpath)
    tmeta = next(c for c in clips if c['name'] == target)

    pcm, frames, ch = prepare_audio(audio_path, log=log)
    duration = frames / 44100.0
    log('[1/4] 音频就绪: %s (%.1f 秒, %d 声道) -> 替换 clip「%s」'
        % (os.path.basename(audio_path), duration, ch, target))
    if tmeta['fmt'] != 0:
        log('      原格式 %s (%.1fs) -> PCM16 (体积会显著增大, 属正常现象)'
            % (FMT_NAMES.get(tmeta['fmt'], tmeta['fmt']), tmeta['length']))

    fsb = build_fsb5_pcm16(pcm, frames, channels=ch)
    log('[2/4] 构建 FSB5 (PCM16): %d 字节' % len(fsb))

    new_ab = replace_clip(fp, target, fsb, duration, channels=ch, log=log)
    log('[3/4] 重打包 bundle: %d 字节 (原 %d)' % (len(new_ab), os.path.getsize(fp)))

    # 备份官方原版: 当前文件不是"我们已装的 mod"时才备份 (涵盖首次/游戏更新两种情况)
    mods = load_mods()
    ent = mods.get(relpath)
    cur_md5 = _md5_file(fp)
    if not (ent and cur_md5 == ent.get('mod_md5') and os.path.exists(backup_path(relpath))):
        bp = backup_path(relpath)
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        shutil.copy2(fp, bp)
        official_md5 = cur_md5
        log('      已备份当前官方原版 -> %s' % os.path.relpath(bp, _HERE))
    else:
        official_md5 = ent.get('official_md5', cur_md5)

    with open(fp, 'wb') as f:
        f.write(new_ab)
    new_md5 = hashlib.md5(new_ab).hexdigest()
    sync_manifest_entry(game, relpath, new_md5, len(new_ab), log=log)

    mods[relpath] = dict(
        clip=target,
        applied_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        source_audio=os.path.abspath(audio_path),
        official_md5=official_md5, mod_md5=new_md5, restored=False)
    save_mods(mods)
    log('[4/4] 已写入游戏文件并登记 Mod (md5=%s)' % new_md5[:12])
    return mods[relpath]

def restore_mod(game_dir, relpath, log=print):
    """还原单个 Mod 为官方原版 (备份回拷 + 清单按备份 md5 同步)"""
    game = resolve_game(game_dir)
    mods = load_mods()
    if relpath not in mods:
        raise RuntimeError('注册表中没有该 Mod: %s' % relpath)
    bp = backup_path(relpath)
    if not os.path.exists(bp):
        raise RuntimeError('官方原版备份不存在: %s' % bp)
    fp = game_file(game, relpath)
    shutil.copy2(bp, fp)
    sync_manifest_entry(game, relpath, _md5_file(bp), os.path.getsize(bp), log=log)
    ent = mods[relpath]
    ent['restored'] = True                 # 用户主动还原: reapply 不应再动它
    save_mods(mods)
    log('已还原: %s' % relpath)

def restore_all(game_dir, log=print):
    mods = load_mods()
    n = 0
    for relpath in list(mods):
        if os.path.exists(backup_path(relpath)):
            restore_mod(game_dir, relpath, log=log)
            n += 1
        else:
            log('跳过 (备份缺失): %s' % relpath)
    log('共还原 %d 个 Mod' % n)
    return n

def mod_status(game_dir, relpath):
    """active=mod生效 / official=用户已还原 / overwritten=被游戏更新覆盖 / missing=文件缺失 / nomod=未登记"""
    game = resolve_game(game_dir)
    mods = load_mods()
    if relpath not in mods:
        return 'nomod'
    fp = game_file(game, relpath)
    if not os.path.isfile(fp):
        return 'missing'
    cur = _md5_file(fp)
    ent = mods[relpath]
    if cur == ent.get('mod_md5'):
        return 'active'
    if cur == ent.get('official_md5'):
        # 同为官方内容: 用户主动还原 -> official; 更新恰好发回同内容 -> overwritten
        return 'official' if ent.get('restored') else 'overwritten'
    return 'overwritten'

STATUS_TEXT = {'active': '● 生效中', 'official': '○ 已还原', 'overwritten': '⚠ 被更新覆盖',
               'missing': '✖ 文件缺失', 'nomod': '— 未安装'}

def list_mods(game_dir):
    """注册表全部条目 + 实时状态"""
    mods = load_mods()
    out = []
    for relpath, ent in mods.items():
        out.append(dict(relpath=relpath, clip=ent.get('clip', '?'),
                        applied_at=ent.get('applied_at', '?'),
                        source=ent.get('source_audio'),
                        status=mod_status_safe(game_dir, relpath)))
    return out

def mod_status_safe(game_dir, relpath):
    try:
        return mod_status(game_dir, relpath)
    except Exception:
        return 'missing'

def reapply_all(game_dir, log=print):
    """对"被更新覆盖"的 Mod 用登记的源音频重新应用 (CAB 模板取自当前文件, 自动适配新版本)"""
    mods = load_mods()
    done, skipped = 0, []
    for relpath, ent in mods.items():
        st = mod_status_safe(game_dir, relpath)
        if st != 'overwritten':
            continue
        src = ent.get('source_audio')
        if not src or not os.path.isfile(src):
            skipped.append(relpath)
            log('跳过 (源音频不存在: %s): %s' % (src, relpath))
            continue
        log('==== 重新应用: %s ====' % relpath)
        apply_mod(game_dir, src, relpath=relpath, clip=ent.get('clip'), log=log)
        done += 1
    log('重应用完成: %d 个; 跳过 %d 个' % (done, len(skipped)))
    return done

def current_state(game_dir):
    """兼容旧接口: 扬升 BGM 条目状态文本"""
    st = mod_status_safe(game_dir, DEFAULT_ENTRY)
    if st == 'nomod':
        return '尚未替换过 (视为原版)', True
    if st in ('official', 'missing'):
        return '当前: 官方原版', True
    if st == 'overwritten':
        return '当前: 官方新版本 (游戏更新覆盖了替换, 可一键重应用)', True
    return '当前: 已替换 (Mod 生效中)', False


# ============ 浏览 / 提取 / 播放 ============
def browse_audio(game_dir, keyword=None):
    """扫描主清单中的音频 .ab (仅磁盘上存在的), 按分类返回 [(分类, relpath, 大小)]"""
    game = resolve_game(game_dir)
    out = []
    for name, (md5, absize) in manifest_entries(game).items():
        if not (name.startswith('audio/') and name.endswith('.ab')):
            continue
        if keyword and keyword.lower() not in name.lower():
            continue
        fp = game_file(game, name)
        if not os.path.isfile(fp):
            continue                       # 未下载 / 打包资源, 不可直接替换
        cat = next((c for c, p in CATEGORIES if name.startswith(p)), '其他音频')
        for c, p in CATEGORIES:            # 前缀最长匹配 (music/ 先于 sound_beta_2/)
            if name.startswith(p):
                cat = c
                break
        out.append((cat, name, os.path.getsize(fp)))
    out.sort(key=lambda x: x[1])
    return out

def find_vgmstream(cfg=None):
    """vgmstream-cli 路径: config 指定 > PATH 查找"""
    if cfg and cfg.get('vgmstream'):
        p = cfg['vgmstream']
        if os.path.isfile(p):
            return p
    return shutil.which('vgmstream-cli') or shutil.which('vgmstream')

def extract_clip(game_dir, relpath, clip_name, out_wav, vgmstream=None, log=print):
    """导出 clip 为 WAV。PCM16 原生解码; Vorbis 需 vgmstream-cli。返回输出路径。"""
    game = resolve_game(game_dir)
    fp = _require_ab(game, relpath)
    clips = list_audio_clips(fp)
    meta = next((c for c in clips if c['name'] == clip_name), None)
    if meta is None:
        raise RuntimeError('bundle 中未找到 clip: %s\n现有: %s'
                           % (clip_name, ', '.join(c['name'] for c in clips)[:400]))
    r, nm, cab, res = _bundle_parts(fp)
    fsb = res[meta['offset']:meta['offset'] + meta['size']]
    if len(fsb) != meta['size']:
        raise RuntimeError('资源区间读取异常 (期望 %d, 实得 %d)' % (meta['size'], len(fsb)))

    if meta['fmt'] == 0:
        # PCM16: 本工具布局 (60B 头 + 8B 采样头) 之后即裸 PCM
        hdr = 68
        pcm = fsb[hdr:]
        ch, fr = meta['channels'], meta['freq']
        if len(pcm) % (ch * 2) != 0:       # 不是本工具布局的 PCM, 交给 vgmstream
            pcm = None
        if pcm is not None:
            with wave.open(out_wav, 'wb') as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(fr)
                w.writeframes(pcm)
            log('已导出 PCM16: %s (%.1f 秒)' % (out_wav, len(pcm) / (ch * 2) / fr))
            return out_wav
    # Vorbis / 未知布局 PCM -> vgmstream-cli
    if not vgmstream:
        raise RuntimeError('该 clip 为 %s 压缩, 导出需要 vgmstream-cli:\n'
                           '  macOS:   brew install vgmstream\n'
                           '  Windows: https://github.com/vgmstream/vgmstream/releases\n'
                           '  然后在设置中指定路径 (或在 PATH 中)' % FMT_NAMES.get(meta['fmt'], meta['fmt']))
    with tempfile.NamedTemporaryFile(suffix='.fsb', delete=False) as tf:
        tf.write(fsb)
        tmpfsb = tf.name
    try:
        cmd = [vgmstream, '-o', out_wav, tmpfsb]
        r2 = subprocess.run(cmd, capture_output=True)
        if r2.returncode != 0 or not os.path.isfile(out_wav):
            raise RuntimeError('vgmstream 解码失败:\n%s' % r2.stderr.decode('utf-8', 'ignore')[:400])
        log('已导出 (vgmstream): %s' % out_wav)
        return out_wav
    finally:
        os.unlink(tmpfsb)

def play_file(path):
    """调用系统播放器播放 (非阻塞)"""
    if sys.platform == 'darwin':
        subprocess.Popen(['afplay', path])
    elif sys.platform == 'win32':
        os.startfile(path)                 # noqa: plat_specific
    else:
        raise RuntimeError('当前平台不支持播放')


# ============ 总览 ============
def studio_status(game_dir):
    game = resolve_game(game_dir)
    mods = list_mods(game_dir)
    cnt = {}
    for m in mods:
        cnt[m['status']] = cnt.get(m['status'], 0) + 1
    return dict(game=game, manifest_version=manifest_version(game),
                mods=mods, counts=cnt)
