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

# ============ 目标资源 ============
# Windows PC 客户端: 游戏根目录 = 含 Arknights_Data 的那一层
REL_AB_WIN = os.path.join('Arknights_Data', 'StreamingAssets', 'AB', 'Windows',
                          'audio', 'sound_beta_2', 'music', 'act54side', 'm_sys_act54side_mainpage.ab')
REL_LIST_WIN = os.path.join('Arknights_Data', 'StreamingAssets', 'AB', 'Windows', 'hot_update_list.json')
# macOS PlayCover (iOS 客户端): 游戏根目录 = 热更资源目录 .../Data/Documents/Bundles
# (国服官方包 com.hypergryph.arknights; 目标 .ab 只存在于热更层, 不在 .app 基础包内)
MAC_DEFAULT_BASE = os.path.expanduser('~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles')
REL_AB_MAC = 'audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab'
MAC_LISTS = ['hot_update_list.json', 'persistent_res_list.json']
ENTRY      = 'audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab'   # 清单中的键
CLIP_NAME  = 'm_sys_act54side_mainpage_loop'                                    # AudioClip 名称
BACKUP_DIR = os.path.join(_HERE, 'backup')


def resolve_paths(base):
    """识别 Windows / macOS(PlayCover) 两种布局, 返回 ab 路径与清单文件列表。

    - Windows: base 为 PC 客户端根目录 (含 Arknights_Data), 清单 totalSize == 文件大小
    - macOS:   base 为 Bundles 热更目录; 条目同时登记在两份清单中,
                且 totalSize 为下载记账值 (实测恒 != 磁盘大小), 只同步 md5/abSize
    - macOS 下 base 留空时自动使用 PlayCover 默认容器路径
    """
    base = (base or '').rstrip('\\/')
    if not base and sys.platform == 'darwin':
        base = MAC_DEFAULT_BASE
    if base and os.path.isdir(os.path.join(base, 'Arknights_Data')):
        ab = os.path.join(base, REL_AB_WIN)
        lists = [os.path.join(base, REL_LIST_WIN)]
        total_eq_size = True
    elif base and all(os.path.isfile(os.path.join(base, f)) for f in MAC_LISTS):
        ab = os.path.join(base, *REL_AB_MAC.split('/'))
        lists = [os.path.join(base, f) for f in MAC_LISTS]
        total_eq_size = False
    else:
        raise RuntimeError(
            '无法识别游戏目录:\n%s\n'
            'Windows: 传入 PC 客户端根目录 (含 Arknights_Data\\StreamingAssets)\n'
            'macOS:   传入 PlayCover 的 .../Data/Documents/Bundles 目录, '
            '或留空自动检测 (国服 com.hypergryph.arknights)' % (base or '(空)'))
    if not os.path.isfile(ab):
        raise RuntimeError('未找到游戏资源文件 (可能尚未下载该资源):\n%s' % ab)
    return dict(base=base, ab=ab, lists=lists, total_eq_size=total_eq_size)


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
    ab_bak = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.exists(ab_bak):
        shutil.copy2(p['ab'], ab_bak)
        for lp in p['lists']:
            shutil.copy2(lp, os.path.join(BACKUP_DIR, os.path.basename(lp) + '.bak'))
        log('      已备份官方原版 -> ' + BACKUP_DIR)

    with open(p['ab'], 'wb') as f:
        f.write(new_ab)
    md5 = hashlib.md5(new_ab).hexdigest()

    # 同步清单 (macOS PlayCover 下条目同时登记于 hot_update_list 与 persistent_res_list)
    for lp in p['lists']:
        j = json.load(open(lp, encoding='utf-8'))
        hit = False
        for it in j['abInfos']:
            if it.get('name') == ENTRY:
                it['md5'] = md5
                it['abSize'] = len(new_ab)
                if p['total_eq_size']:      # Windows: totalSize == 文件大小; iOS: 保留下载记账值
                    it['totalSize'] = len(new_ab)
                hit = True
        if not hit:
            raise RuntimeError('清单 %s 中未找到条目: %s' % (os.path.basename(lp), ENTRY))
        with open(lp, 'w', encoding='utf-8', newline='') as f:
            f.write(json.dumps(j, separators=(',', ':'), ensure_ascii=False))
        log('      清单已同步: %s' % os.path.basename(lp))
    log('[4/4] 已写入游戏文件并同步清单 (md5=%s)' % md5)
    log('完成! 启动游戏后在主界面切换「扬升」主题即可生效。')
    return md5


# ============ 7. 还原官方原版 ============
def restore(game_dir, log=print):
    """从备份还原官方 .ab 与各清单文件"""
    p = resolve_paths(game_dir)
    ab_bak = os.path.join(BACKUP_DIR, 'm_sys_act54side_mainpage.ab.bak')
    if not os.path.exists(ab_bak):
        raise RuntimeError('备份不存在, 可能从未替换过: ' + BACKUP_DIR)
    shutil.copy2(ab_bak, p['ab'])
    restored = []
    for lp in p['lists']:
        lb = os.path.join(BACKUP_DIR, os.path.basename(lp) + '.bak')
        if os.path.exists(lb):
            shutil.copy2(lb, lp)
            restored.append(os.path.basename(lp))
    log('已还原官方原版 (Aria of the Soul)。清单还原: %s' % (', '.join(restored) or '无'))
    log('注意: 若替换后游戏更新过, 建议在游戏内重新校验资源确保清单一致。')


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
    ap = argparse.ArgumentParser(description='明日方舟「扬升」主题主界面 BGM 替换工具 (Windows PC / macOS PlayCover)')
    ap.add_argument('--game', help='游戏目录: Windows 传 PC 客户端根目录(含 Arknights_Data); '
                                   'macOS 传 PlayCover 的 .../Data/Documents/Bundles 目录, 留空自动检测')
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
