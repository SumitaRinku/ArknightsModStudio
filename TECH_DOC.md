# 明日方舟 BGM 替换技术文档（Windows PC / macOS PlayCover）

> 项目：将主界面「扬升」主题背景音乐（Aria of the Soul）替换为自定义曲目
> 平台：Windows PC 客户端 / macOS PlayCover（iOS 客户端）· Unity 2021.3.39f1 / IL2CPP
> 目标文件：`audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab`
> 文档版本：2026-09-28（新增第 11 节 macOS PlayCover 适配）

---

## 目录

1. [游戏资源存取架构](#1-游戏资源存取架构)
2. [AssetBundle 格式分析（含自定义 LZ4AK）](#2-assetbundle-格式分析)
3. [目标定位：从 1.3 万个 bundle 到 1 个文件](#3-目标定位)
4. [音频数据格式：AudioClip 与 FSB5](#4-音频数据格式)
5. [替换实现：完整数据流](#5-替换实现)
6. [校验机制与绕过策略](#6-校验机制)
7. [验证方法](#7-验证方法)
8. [更新对修改的影响与恢复](#8-更新影响)
9. [工具清单与使用说明](#9-工具清单)
10. [扩展方向](#10-扩展方向)
11. [macOS PlayCover 适配](#11-macos-playcover-适配)

---

## 1. 游戏资源存取架构

### 1.1 资源层级

```
┌─────────────────────────────────────────────────────┐
│  基础包（随客户端安装，只读语义）                        │
│  Arknights_Data/StreamingAssets/AB/Windows/           │
│    ├── hot_update_list.json    ← 全量资源索引(13177条)  │
│    ├── 5bf3460e...idx          ← 分包索引              │
│    └── audio/.../xxx.ab        ← UnityFS AssetBundle  │
├─────────────────────────────────────────────────────┤
│  热更包（按需下载，可写）                                │
│  Arknights_Data/PersistentData/Bundles/              │
│    ├── persistent_res_list.json ← 热更索引             │
│    └── *.ab                          │
└─────────────────────────────────────────────────────┘
```

- **基础包**：安装时全量存在，音频、UI 等静态资源主要在这里。
- **热更包**：版本迭代时新增/修改的资源，运行时优先级高于基础包同名文件。
- 命名约定：`m_sys_*` 系统界面 BGM、`m_bat*_*` 战斗 BGM、`actXXside` 为side story 活动代号（act54side = P3R 联动「月行水上」）。

### 1.2 hot_update_list.json 结构

单行紧凑 JSON，13177 个条目：

```json
{
  "versionId": "26-08-16-14-00-43_415873",
  "abInfos": [
    {
      "name": "audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab",
      "hash": "bd4a0a88...",   ← 用途为版本比对（保持不变可避免触发重下）
      "md5": "73f5691a...",   ← 已验证 = .ab 文件本身的 MD5
      "totalSize": 1965108,    ← = 文件字节数
      "abSize": 1965108
    }
  ],
  "manifestName": "5bf3460e....idx",
  "manifestVersion": "V077",
  "packInfos": null
}
```

关键实验结论（通过逐一计算验证）：
- `md5` = **文件本身的 MD5**（改文件后必须同步更新此字段）
- `totalSize` / `abSize` = 文件字节数
- `hash` = 未识别算法（非整包/分片/CAB/resource 的 MD5、非 CRC32/SHA1），推测为内容指纹，用于与服务端清单比对决定是否重下资源

---

## 2. AssetBundle 格式分析

### 2.1 UnityFS 容器结构（version 8）

```
"UnityFS\0"                       8B  魔数
int32  version = 8                4B
string ver    = "5.x.x\0"
string rev    = "2021.3.39f1\0"
int64  size                   ← 整个文件大小
int32  compressedBlocksInfoSize    ← blocksInfo 压缩后字节数
int32  uncompressedBlocksInfoSize
int32  flags = 0x243
  ├─ 0x003 = blocksInfo 压缩方式 (3 = LZ4HC)
  ├─ 0x040 = BLOCKS_AND_DIR_COMBINED
  └─ 0x200 = BLOCK_INFO_NEEDS_ALIGNMENT（数据区 16 对齐）
[align 16]
blocksInfo (LZ4HC 压缩):
  16B  hash（本作为全零）
  int32 nblk;  { uint32 usize; uint32 csize; uint16 flag } × nblk
  int32 ndir;  { int64 offset; int64 size; int32 status; cstring name } × ndir
[align 16 (flags & 0x200)]
数据块（每块独立压缩，逐块解压后拼接 = 所有 CAB/resS 文件连续存放）
```

节点表中 `offset` 指向**解压后数据流**中的位置，游戏引擎按节点表切片读取。

### 2.2 自定义 LZ4AK 压缩（flag = 4）

本作的音频 bundle 数据块大量使用 flag=4 的私有变体，标准 LZ4 解码会失败（error code 10）。经逆向分析，其对标准 LZ4 字节流做两处变换：

1. **token 高低 nibble 互换**：`token = (lit << 4) | match` ↔ `token = (match << 4) | lit`
2. **match offset 两字节字节序交换**：`offset[0] ↔ offset[1]`

修复实现见 `_bgm_mod/akparse.py` 的 `fix_lz4ak()`：遍历解码令牌流，逐个 token 换 nibble、逐个 offset 交换字节，还原为标准 LZ4 后调用 `lz4.block.decompress`。

### 2.3 重要发现：标准压缩标志同样被接受

目标 bundle 的 blocksInfo 本身就用**标准 LZ4HC (flag 3)** 压缩、数据块大多**不压缩 (flag 0)**——证明游戏运行时的解压器完全兼容标准压缩。因此**重打包时全部使用标准 LZ4HC 即可，无需实现 LZ4AK 压缩**（只需解压能力，用于读取原文件）。

---

## 3. 目标定位

### 3.1 候选筛选

1. 在 `hot_update_list.json` 中按 `act54side` 关键字过滤出联动相关 bundle；
2. 用 `akparse.py` 解析 + UnityPy 枚举所有 AudioClip（`scan_music.py` / `list_clips.py`）；
3. 字符串扫描（`scan_str2.py`）确认无独立曲目名表——音频即资源本体。

### 3.2 声纹比对确认

用 FMOD 解码候选 FSB5 为 WAV，与参考音频（Aria of the Soul）做**包络相关度**分析（`compare.py`，50ms 窗 RMS 包络 + 互相关归一化）：

| 候选 clip | 相关度 |
|---|---|
| **m_sys_act54side_mainpage_loop** | **0.881** ✓ |
| m_sys_act54side_intro | 0.71 |
| m_bat1/bat2_act54side_* | < 0.5 |

确认主界面「扬升」主题 BGM = `m_sys_act54side_mainpage.ab` 中的 `m_sys_act54side_mainpage_loop`。

### 3.3 目标 bundle 结构（极简，利于替换）

```
node 0: CAB-909b7688....           4576B   序列化文件 (AssetBundle + AudioClip 两个对象)
node 1: CAB-909b7688....resource 1962752B  纯 FSB5 音频数据（无其他资源混杂）
```

bundle 内只有一个 AudioClip，`.resource` 文件整体即其音频数据（offset=0, size=全文），替换不会产生地址重排问题。

---

## 4. 音频数据格式

### 4.1 AudioClip 序列化字段（修改对象）

| 字段 | 原值 | 修改后 |
|---|---|---|
| m_Name | m_sys_act54side_mainpage_loop | 不变 |
| m_LoadType | 2 (流式) | 不变 |
| m_Channels / m_Frequency / m_BitsPerSample | 2 / 44100 / 16 | 不变 |
| m_Length | 165.652 | 新曲目时长 |
| m_CompressionFormat | 1 (Vorbis) | **0 (PCM)** |
| m_Resource.m_Source | archive:/CAB-.../...resource | 不变 |
| m_Resource.m_Offset / m_Size | 0 / 1962752 | 0 / 新FSB5大小 |

> 为什么改成 PCM 而不是重新编码 Vorbis：Vorbis 编码需要带内 seek 表（VORBISDATA chunk 含逐块偏移表，供 FMOD 流式 seek），自造该表复杂且易错；PCM 无损、构造简单、FMOD 原生支持。代价是体积膨胀（1.9MB → 39MB），但流式加载下不影响运行时内存。

### 4.2 FSB5 容器格式（FMOD 音频容器）

```
偏移   大小   内容
0x00   4     "FSB5"
0x04   4     version = 1
0x08   4     numSamples = 1
0x0C   4     sampleHeadersSize
0x10   4     nameTableSize = 0
0x14   4     dataSize
0x18   4     mode (2 = PCM16, 15 = Vorbis)
0x1C   8     zero
0x24   16    hash（可全零）
0x2C   8     dummy
—— 采样头（每个样本 8B 位域 + 可变 chunk）——
bit0        next_chunk = 0（无元数据 chunk，原版 Vorbis 有 VORBISDATA chunk，PCM 无需）
bit1-4      frequency code (8 = 44100Hz)
bit5        channels - 1
bit6-33     dataOffset / 16
bit34-63    总样本帧数
—— 数据区 ——
裸 PCM16 小端交错数据
```

原版 Vorbis FSB5 只有 VORBISDATA chunk、**无 LOOP chunk**（循环由 Unity AudioSource 层实现），故 PCM 版本无需任何 chunk，结构反而更简单。

---

## 5. 替换实现

完整数据流（`modlib.py`）：

```
源 WAV (44.1k/16bit/stereo)
  │ ① wave 读取 PCM
  ▼
FSB5-PCM16 容器（60B 头 + 8B 采样头 + PCM 数据）
  │ ② struct.pack 构造
  ▼
原 bundle ──akparse 解压──► CAB + .resource
  │                          │
  │                          └─ CAB: UnityPy 加载 → 改 AudioClip
  │                              (m_Length/m_CompressionFormat/m_Resource.m_Size) → save()
  ▼
新 bundle：CAB(新) + FSB5(新) 按原节点名/status 重组
  │ ③ blocksInfo 用标准 LZ4HC 压缩，数据块逐块 LZ4HC/不压缩
  │    flags 保持 0x243，版本号/引擎号与原版一致
  ▼
覆盖写入原 .ab 路径
  │ ④
  ▼
更新 hot_update_list.json：md5/totalSize/abSize ← 新文件实际值（hash 保持不变）
```

关键工程细节：
- **CAB 重序列化**：UnityPy `env.file.save()` 输出与原文件对象数据字节级一致（已验证 `get_raw_data()` 逐字节比对），仅类型元数据重排导致文件缩短 784B——不影响加载。
- **备份策略**：首次替换时将官方原版 `.ab` 与 `hot_update_list.json` 复制到 `_bgm_mod/backup/`，之后无论怎么切换曲目都从 CAB 模板重新生成（模板从当前游戏文件解析；还原时直接回拷备份）。

---

## 6. 校验机制

| 层级 | 机制 | 应对 |
|---|---|---|
| 本地清单 | `md5` 字段比对文件 MD5 | 改后同步更新 md5/totalSize 字段 ✓ |
| 服务端清单 | `versionId`/`hash` 与服务器比对 | 保留 `hash` 不动，日常启动不触发重下 |
| 启动器/patcher | 版本更新时按服务器清单校验文件 | **无法绕过**，见第 8 节 |
| IL2CPP 代码完整性 | 游戏本体代码签名 | 未触碰（只改资源，无封号面） |

实测依据：启动器日志（`games.log`）中只有版本比对记录，无逐文件 MD5 巡检；`md5` 字段值经验证就是文件 MD5 本身。

---

## 7. 验证方法

1. **容器往返**：`akparse` 重新解析新 bundle，节点偏移/大小/内容与写入值一致；
2. **对象往返**：UnityPy 回读新 CAB，`m_Length` / `m_CompressionFormat` / `m_Resource.m_Size` 与设定值一致；
3. **FSB5 解析**：`fsb5` 库解析新资源，mode=PCM16、44100Hz、2ch、帧数正确；
4. **运行时解码**（最关键）：用 **FMOD 运行时**（游戏同款解码路径，`fmod_toolkit`）解码新 FSB5，输出 WAV 与源文件**逐样本比对 100% 一致**（2000 万+ 采样，最大差 0）；
5. **清单一致性**：新文件 MD5 == 清单 `md5` 字段，`totalSize` == 文件大小。

---

## 8. 更新影响

**结论：版本更新或资源热更会覆盖修改，需要重新应用。**

具体情形：

| 情形 | 影响 | 说明 |
|---|---|---|
| 日常启动（无版本变化） | 无影响 | `hash` 未变，服务端不重下该文件 |
| **资源热更**（服务器改 versionId，act54side 相关资源变动） | 修改被覆盖 | patcher 会按服务端清单重下 `m_sys_act54side_mainpage.ab`，同时 `hot_update_list.json` 被服务器版替换 |
| **客户端版本更新** | 修改被覆盖 | StreamingAssets 目录整体更新，且新版本可能改 bundle 布局 |
| 官方修复了 act54side 音频 bug | 同上 | 该文件被重下 |

恢复成本极低（这正是做 GUI 工具的原因）：
1. 更新完成后打开「BGM切换器」；
2. 若备份仍是当前游戏版本的原版 → 直接点「替换 BGM」即可（工具从**当前**游戏文件提取 CAB 模板，永远适配当前版本）；
3. 若工具报解析失败（bundle 布局变版）→ 先点「还原官方原版」清掉旧备份，让游戏重新下载原文件，再重新替换。

> 注意：`backup/` 中的备份与游戏版本绑定，跨版本更新后**不要**直接用旧备份还原（可能版本不匹配），应先还原再让游戏重新校验下载。

---

## 9. 工具清单

`f:\Arknights\Arknights Game\_bgm_mod\` 下：

| 文件 | 用途 |
|---|---|
| **BGM切换器.bat** | 双击启动 GUI（推荐日常使用） |
| **mod_gui.py** | Tkinter 界面：三选一替换 / 还原原版，实时日志 |
| **modlib.py** | 核心库（读 WAV → FSB5 → 改 CAB → 重打包 → 部署 → 更新清单；含还原）。也支持 CLI：`python modlib.py --apply 1|2|3` / `--restore` |
| akparse.py | 自定义 UnityFS/LZ4AK 解析器（逆向成果，只读） |
| build_mod.py / deploy.py | 首次实施的一次性脚本（已被 modlib 取代，留档） |
| compare.py / extract_fsb.py / list_clips.py / scan_*.py | 分析期工具（目标定位、声纹比对） |
| backup/ | 官方原版 .ab 与 hot_update_list.json 备份 |
| output/ | 构建产物与预览 WAV |

**GUI 使用**：双击 `BGM切换器.bat` → 选中曲目 → 「替换 BGM」→ 启动游戏，主界面切换到「扬升」主题；「还原官方原版」可随时恢复。

**依赖**：Python 3.12 + UnityPy 1.25.3 + lz4 + fsb5 + fmod_toolkit（路径已内置于脚本，无需配置环境变量）。

**曲目要求**：44.1kHz / 16bit / 立体声 WAV（当前三首均满足；新增曲目需先转换格式，或扩展 `modlib.SONGS` 列表）。

---

## 10. 扩展方向

- **任意 BGM 替换**：`modlib.apply_song()` 参数化目标 bundle 路径 + clip 名即可推广到其他主题（如战斗 BGM `m_bat*`）；
- **体积优化**：接入 Vorbis 编码器（如 `vorbis-tools`）重造 VORBISDATA seek 表，可把 39MB 压回 ~2MB——复杂度高，当前流式加载下无必要；
- **免覆盖安装**：将 mod bundle 放入 `PersistentData/Bundles` 并登记 `persistent_res_list.json`，利用热更优先级覆盖基础包文件——不改动官方文件，更新时自动失效，比当前方案更干净；
- **自动化更新适配**：GUI 启动时检测游戏版本号变化，提示重新提取 CAB 模板。

---

## 11. macOS PlayCover 适配（2026-09-28）

### 11.1 资源位置差异

iOS 客户端（PlayCover 安装的国服 ipa）的目标文件**不在 .app 基础包**内
（`明日方舟.app/Data/Raw/AB/IOS/hot_update_list.json` 仅 3179 条基础条目，无 act54side 音频），
只存在于热更层：

```
~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles/
  ├── hot_update_list.json          ← 15217 条（含 .idx 分包索引）
  ├── persistent_res_list.json      ← 11375 条
  └── audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab
```

工具的「游戏目录」在该平台即指此 `Bundles` 目录（留空时自动检测上述默认容器路径）。

### 11.2 双清单与字段语义差异（400 条抽样实测验证）

| 字段 | Windows | iOS (PlayCover) |
|---|---|---|
| 登记清单 | 仅 `hot_update_list.json` | `hot_update_list.json` + `persistent_res_list.json` **双清单，两份都要同步** |
| `md5` | = 文件 MD5 | = 文件 MD5（相同）→ 替换后同步 |
| `abSize` | = 文件大小 | = 文件大小（400/400 抽样一致）→ 替换后同步 |
| `totalSize` | = 文件大小 | 恒 ≠ 磁盘大小（下载记账值）→ **保持不动** |
| `hash` | 版本指纹 | 版本指纹 → **保持不动** |

### 11.3 bundle 本体：与 Windows 完全同构

实测解析 iOS 端目标 bundle：`version=8 / flags=0x243 / 同名 CAB-909b7688... /
双节点布局 / AudioClip 165.652s Vorbis`——与 3.3 节 Windows 端结构逐字段一致。
因此 FSB5-PCM16 构建、CAB 补丁、UnityFS 重打包整条链路**零改动直接复用**
（CAB 重序列化同样缩短 784B）；LZ4AK 私有压缩变体在两端同样存在，`akparse` 均可解。

### 11.4 环境与验证

- Homebrew Python 的 tkinter 独立打包：`brew install python-tk@<小版本>`（venv 前的必备步骤）
- 音频转换可用系统自带 `afconvert` 替代 ffmpeg：`afconvert -f WAVE -d LEI16@44100 -c 2 in.mp3 out.wav`
- 2026-09-27 实测（macOS + PlayCover，替换为 227.2s PCM 曲目）：容器往返、AudioClip 回读、
  PCM 逐字节比对（40085248 B 全等）、双清单 md5/abSize 一致性、原版备份 md5 校验全部通过

---

## 附：关键逆向数据速查

```
目标 bundle:  audio/sound_beta_2/music/act54side/m_sys_act54side_mainpage.ab
官方 md5:     73f5691a20391b9e601173952b514899 (1965108 B)
CAB 节点:     CAB-909b7688d37e27bfc183311aadaf6651 (4576 B, status=0x4)
resource 节点: CAB-909b7688d37e27bfc183311aadaf6651.resource (1962752 B)
AudioClip:    path_id=4457544689111580993, m_Name=m_sys_act54side_mainpage_loop
原音频:       FSB5/Vorbis, 44100Hz, 2ch, 165.652s, 7305261 帧
bundle flags: 0x243 (blocksInfo=LZ4HC, combined, aligned)

iOS (PlayCover) 端:
官方 md5:     d9de3a69a27da4e56eaf2add4daa5f57 (1965126 B, totalSize=1931939)
所在位置:     ~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles/
              (不在 .app 基础包内; 双清单登记, 见第 11 节)
```

> **2026-09 更新附注（本文档写作后游戏已更新）**：2026-09-18 前后官方更新把该文件并入基础包并替换为完整版 PCM：
> - 新文件 39283926 B（md5 `ad13cd9b9b882c32523fbcd8eb26fd73`），`totalSize == abSize`
> - resource 节点 40042564 B，FSB5/**PCM16** 44100Hz 2ch 10010624 帧（226.998s，即完整版 Aria of the Soul）
> - 双节点布局、flags 0x243、version 8、CAB 名均未变 → 本工具链路对新版依然有效（已实测解析/重打包通过）
> - `PersistentData\Bundles\hot_update_list.json` 中该条目仍残留旧热更版记录（md5 `73f5691a...`，pid=lpack_music2），且对应文件不存在于 PersistentData——实测该失配不影响游戏运行，说明运行时不做跨层强校验，故本工具只需同步 StreamingAssets 层清单。
> - 据此修正第 6/8 节的一个实战教训：启动期报「资源加载异常 错误0」往往伴随网络故障（资源校验/重下走网络），排障时应先排查网络，再怀疑文件。
>
> 文中示例路径为开发者本机环境，仅供参考。
