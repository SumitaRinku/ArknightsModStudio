# 明日方舟 PC 客户端自定义 UnityFS 完整解析
# 格式: "UnityFS\0" + int32(version=8) + "5.x.x\0"? -- 实际为:
#   sig "UnityFS\0" + version int32(8) + ver_str "5.x.x\0" + rev_str "2021.3.39f1\0"
#   + size int64 + cbs int32 + ubs int32 + flags int32 + align16 + blocksInfo
#   + align16 + 数据块
# 块压缩标志 4 = LZ4AK (LZ4 token nibble 互换 + offset 字节交换)
import struct, sys

def _decomp(flag, data, usize, ak=True):
    if flag == 0:
        return bytes(data)
    if flag == 1:
        import lzma
        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(bytes(data))
    if flag in (2, 3):
        import lz4.block
        return lz4.block.decompress(bytes(data), uncompressed_size=usize)
    if flag == 4:
        if not ak:
            raise ValueError('LZ4AK 不支持')
        import lz4.block
        fixed = fix_lz4ak(bytes(data), usize)
        return lz4.block.decompress(fixed, uncompressed_size=usize)
    raise ValueError(f'未知压缩标志 {flag}')

def fix_lz4ak(data, usize):
    """将 LZ4AK 字节流修复为标准 LZ4 (就地变换)"""
    fixed = bytearray(data)
    ip = 0; op = 0; size = len(fixed)
    def read_extra(ip):
        length = 0
        while ip < size:
            b = fixed[ip]; length += b; ip += 1
            if b != 0xFF:
                break
        return length, ip
    while ip < size:
        token = fixed[ip]
        lit = token & 0x0F
        match = (token >> 4) & 0x0F
        fixed[ip] = (lit << 4) | match
        ip += 1
        if lit == 0x0F:
            e, ip = read_extra(ip)
            lit += e
        ip += lit; op += lit
        if op >= usize:
            break
        if ip + 2 > size:
            break
        fixed[ip], fixed[ip+1] = fixed[ip+1], fixed[ip]
        ip += 2
        if match == 0x0F:
            e, ip = read_extra(ip)
            match += e
        op += match + 4
    return bytes(fixed)

def _align16(x):
    return (x + 15) & ~15

def parse(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'UnityFS\0'
    off = 8
    version, = struct.unpack('>i', d[off:off+4]); off += 4
    def rstr():
        nonlocal off
        e = d.index(b'\0', off)
        s = d[off:e]; off = e + 1
        return s
    ver = rstr(); rev = rstr()
    size, cbs, ubs, flags = struct.unpack('>QIii', d[off:off+20]); off += 20
    if version >= 7:
        off = _align16(off)
    info = _decomp(flags & 0x3F, d[off:off+cbs], ubs, ak=False)
    p = 16
    (nblk,) = struct.unpack('>i', info[p:p+4]); p += 4
    blocks = []
    for _ in range(nblk):
        us, cs, fl = struct.unpack('>IIH', info[p:p+10]); p += 10
        blocks.append((us, cs, fl))
    (ndir,) = struct.unpack('>i', info[p:p+4]); p += 4
    nodes = []
    for _ in range(ndir):
        offset, nsize, status = struct.unpack('>qqi', info[p:p+20]); p += 20
        e = info.index(b'\0', p)
        name = info[p:e].decode(); p = e + 1
        nodes.append(dict(name=name, offset=offset, size=nsize, status=status))
    if flags & 0x200:
        off = _align16(off + cbs)
    data = bytearray()
    for us, cs, fl in blocks:
        data += _decomp(fl, d[off:off+cs], us)
        off += cs
    return dict(version=version, flags=flags, blocks=blocks, nodes=nodes,
                data=bytes(data), ver=ver, rev=rev)

if __name__ == '__main__':
    for p in sys.argv[1:]:
        r = parse(p)
        print('===', p)
        print(' version=%d flags=0x%x blocks=%d dataLen=%d' % (r['version'], r['flags'], len(r['blocks']), len(r['data'])))
        for n in r['nodes']:
            print('  node: %-46s offset=%d size=%d status=0x%x' % (n['name'], n['offset'], n['size'], n['status']))
