# -*- coding: utf-8 -*-
"""明日方舟「扬升」主题主界面 BGM 替换核心库 (可移植版)
将「扬升」主题主界面 BGM (m_sys_act54side_mainpage_loop, Aria of the Soul)
替换为指定的 44.1kHz/16bit/立体声 WAV, 或还原为官方原版。

不修改游戏程序本体, 只替换一个 AssetBundle 资源文件并同步清单 md5。
"""
import sys, os, io, json, wave, struct, shutil, hashlib

# UnityPy / lz4 依赖: 优先使用 pip 安装的版本; 其次找脚本旁的 pkgs 目录
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, 'pkgs'), r'C:\Users\09\.local\lib\unitypy_pkgs'):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
sys.path.insert(0, _HERE)   # 本目录优先, 避免外部同名模块遮蔽 akparse
import lz4.block
import UnityPy
from akparse import parse

# ============ 目标资源 (相对游戏根目录) ============
REL_AB   = r'Arknights_Data\StreamingAssets\AB\Windows\audio\sound_beta_2\music\act54side\m_sys_act54side_mainpage.ab'
REL_LIST = r'Arknights_Data\StreamingAssets\AB\Windows\hot_update_list.json'
ENTRY      = 'audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab'   # 清单中的键
CLIP_NAME  = 'm_sys_act54side_mainpage_loop'                                    # AudioClip 名称
BACKUP_DIR = os.path.join(_HERE, 'backup')


def resolve_paths(base):
    """校验游戏根目录并返回 ab / 清单路径。"""
    base = (base or '').rstrip('\\/')
    ab = os.path.join(base, REL_AB)
    if not base or not os.path.isfile(ab):
        raise RuntimeError(
            '未找到游戏资源文件, 请确认选择的是明日方舟 PC 客户端根目录\n'
            '(应包含 Arknights_Data\\StreamingAssets 子目录):\n%s' % base)
    return dict(base=base, ab=ab, list=os.path.join(base, REL_LIST))


# ============ 1. WAV 读取 ============
def read_wav(path):
    w = wave.open(path, 'rb')
    nch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    if (nch, sw, sr) != (2, 2, 44100):
        w.close()
        raise ValueError('仅支持 44.1kHz / 16bit / 立体声 WAV, 当前: ch=%d width=%d rate=%d\n'
                         '可用 ffmpeg 转换: ffmpeg -i 输入 -ar 44100 -sample_fmt s16 -ac 2 输出.wav'
                         % (nch, sw, sr))
    pcm = w.readframes(nf)
    w.close()
    return pcm, nf


# ============ 2. FSB5 (PCM16) 构建 ============
def build_fsb5_pcm16(pcm, samples, channels=2, freq_code=8):
    """FSB5 头 60 字节 + 8 字节采样头 (无 chunk) + PCM 数据, 布局与原版一致"""
    header = struct.pack('<4sIIIIII8s16s8s',
        b'FSB5', 1, 1, 8, 0, len(pcm), 2, b'\x00'*8, b'\x00'*16, b'\x00'*8)
    q = (freq_code << 1) | ((channels - 1) << 5) | (samples << 34)
    return header + struct.pack('<Q', q) + pcm


# ============ 3. 修改 CAB 中的 AudioClip ============
def patch_cab(orig_cab, fsb_size, duration):
    env = UnityPy.load(io.BytesIO(orig_cab))
    hit = False
    for obj in env.objects:
        if obj.type.name == 'AudioClip':
            d = obj.read()
            if d.m_Name != CLIP_NAME:
                continue
            d.m_Length = float(duration)
            d.m_CompressionFormat = 0            # PCM
            d.m_Resource.m_Offset = 0
            d.m_Resource.m_Size = fsb_size
            d.save()
            hit = True
    if not hit:
        raise RuntimeError('CAB 中未找到 AudioClip: %s\n游戏可能已更新, 请等待本工具适配或提 issue。' % CLIP_NAME)
    return env.file.save()


# ============ 4. UnityFS bundle 重打包 ============
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


# ============ 5. 当前状态查询 ============
def _md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def current_state(game_dir):
    """返回 (状态文本, 是否原版)。用于界面提示。"""
    p = resolve_paths(game_dir)
    ab_bak = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    if not os.path.exists(ab_bak):
        return '尚未替换过 (视为原版)', True
    if _md5_file(p['ab']) == _md5_file(ab_bak):
        return '当前: 官方原版', True
    return '当前: 已替换 (非官方文件)', False


# ============ 6. 完整替换流程 ============
def apply_song(wav_path, game_dir, log=print):
    """将指定 WAV 替换进游戏 (首次运行自动备份官方原版)"""
    p = resolve_paths(game_dir)
    pcm, frames = read_wav(wav_path)
    duration = frames / 44100.0
    log('[1/4] 读取 WAV: %.1f 秒, %d 字节' % (duration, len(pcm)))

    fsb = build_fsb5_pcm16(pcm, frames)
    log('[2/4] 构建 FSB5 (PCM16): %d 字节' % len(fsb))

    r = parse(p['ab'])
    nodes_meta = r['nodes']
    if len(nodes_meta) < 2 or not nodes_meta[1]['name'].endswith('.resource'):
        raise RuntimeError('bundle 结构与预期不符 (节点数=%d), 游戏可能已更新' % len(nodes_meta))
    orig_cab = r['data'][:nodes_meta[0]['size']]
    new_cab = patch_cab(orig_cab, len(fsb), duration)
    new_ab = build_bundle(
        [dict(name=nodes_meta[0]['name'], data=new_cab, status=nodes_meta[0]['status']),
         dict(name=nodes_meta[1]['name'], data=fsb,    status=nodes_meta[1]['status'])],
        version=r['version'], flags=r['flags'], ver=r['ver'], rev=r['rev'])
    log('[3/4] 重打包 bundle: %d 字节 (原 %d)' % (len(new_ab), os.path.getsize(p['ab'])))

    # 备份官方原版 (仅首次)
    ab_bak  = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    lst_bak = os.path.join(BACKUP_DIR, 'hot_update_list.json.bak')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.exists(ab_bak):
        shutil.copy2(p['ab'], ab_bak)
        shutil.copy2(p['list'], lst_bak)
        log('      已备份官方原版 -> ' + BACKUP_DIR)

    with open(p['ab'], 'wb') as f:
        f.write(new_ab)
    md5 = hashlib.md5(new_ab).hexdigest()

    j = json.load(open(p['list'], encoding='utf-8'))
    hit = False
    for it in j['abInfos']:
        if it.get('name') == ENTRY:
            it['md5'] = md5
            it['totalSize'] = len(new_ab)
            it['abSize'] = len(new_ab)
            hit = True
    if not hit:
        raise RuntimeError('清单中未找到条目: ' + ENTRY)
    with open(p['list'], 'w', encoding='utf-8', newline='') as f:
        f.write(json.dumps(j, separators=(',', ':'), ensure_ascii=False))
    log('[4/4] 已写入游戏文件并同步 hot_update_list.json (md5=%s)' % md5)
    log('完成! 启动游戏后在主界面切换「扬升」主题即可生效。')
    return md5


# ============ 7. 还原官方原版 ============
def restore(game_dir, log=print):
    """从备份还原官方 .ab 与 hot_update_list.json"""
    p = resolve_paths(game_dir)
    ab_bak  = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    lst_bak = os.path.join(BACKUP_DIR, 'hot_update_list.json.bak')
    if not (os.path.exists(ab_bak) and os.path.exists(lst_bak)):
        raise RuntimeError('备份不存在, 可能从未替换过: ' + BACKUP_DIR)
    shutil.copy2(ab_bak, p['ab'])
    shutil.copy2(lst_bak, p['list'])
    log('已还原官方原版 (Aria of the Soul)。')
    log('注意: 若替换后游戏更新过, 建议再运行启动器「完整性检查」确保清单一致。')


# ============ CLI ============
def _saved_game_dir():
    cfg = os.path.join(_HERE, 'config.json')
    if os.path.exists(cfg):
        try:
            return json.load(open(cfg, encoding='utf-8')).get('game_dir', '')
        except Exception:
            pass
    return ''

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='明日方舟「扬升」主题主界面 BGM 替换工具')
    ap.add_argument('--game', help='明日方舟 PC 客户端根目录 (含 Arknights_Data)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--apply', metavar='WAV', help='替换为指定 WAV (44.1kHz/16bit/立体声)')
    g.add_argument('--restore', action='store_true', help='还原官方原版')
    g.add_argument('--status', action='store_true', help='查看当前替换状态')
    a = ap.parse_args()
    game = a.game or _saved_game_dir()
    if a.status:
        print(current_state(game)[0])
    elif a.restore:
        restore(game)
    else:
        print('替换为: ' + a.apply)
        apply_song(a.apply, game)
