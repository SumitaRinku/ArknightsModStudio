# ArknightsModStudio

> **请勿分享、请勿传播。**
> 如果你找到这个仓库，就当是捡到的宝藏，自己偷偷用、偷偷享受就好。
> 转发到群里、贴吧、社交平台的瞬间，它离失效就不远了。

明日方舟**音频 Mod 工作台**，支持 **Windows PC 客户端** 与 **macOS PlayCover（iOS 客户端）**。

不只主界面 BGM——**任意音乐、干员语音（中/日）、音效、氛围音**都能换成你自己的音频，还能把游戏里的曲子和语音导出成 WAV 收藏。

- **BGM 快速替换**：一键把「扬升」主题主界面 BGM（Aria of the Soul）换成任意歌曲
- **音频工坊**：浏览全部 1700+ 音频资源包（按分类/关键词过滤），包内逐条列出 Clip（曲名/时长/格式），试听、导出 WAV、指哪换哪
- **Mod 管理**：所有替换登记在册，逐个/一键还原；游戏更新覆盖后自动检测，一键重新应用
- **自动格式转换**：MP3/FLAC/M4A 直接选用，自动转为合规格式（macOS 免安装，Windows 需 ffmpeg）
- 不改游戏程序，只替换音频资源包并同步校验清单；首次替换自动备份官方原版
- 本仓库**不含任何游戏资源、官方文件或音乐文件**，替换音频由使用者自备

## 环境要求

- Windows + 明日方舟 PC 官方客户端，或 macOS + PlayCover 运行的明日方舟（iOS 国服客户端，均测试于 2026-09/10 的 V077 版本）
- Python 3.10 或更高（自带 Tkinter；GUI 基于 [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) 暗色现代主题，随 `requirements.txt` 一并安装；macOS 用 Homebrew Python 时 tkinter 需另装 `python-tk`，见「安装」）
- 可选：[vgmstream](https://github.com/vgmstream/vgmstream)（试听/导出 Vorbis 压缩的官方音频时需要；替换功能不需要它）

## 安装

```bash
git clone <本仓库地址>
cd ArknightsModStudio
pip install -r requirements.txt
```

不会用 git 的话：下载 ZIP 解压后，在文件夹里打开终端执行 `pip install -r requirements.txt`。

**macOS**（Homebrew Python 的 tkinter 是独立包，必须先装 `python-tk`）：

```bash
git clone <本仓库地址>
cd ArknightsModStudio
brew install python-tk@3.14          # 版本号对应 brew 安装的 python3 小版本
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**vgmstream（可选，用于试听/导出官方 Vorbis 音频）**：

- macOS：`brew install vgmstream`，或从 [GitHub Releases](https://github.com/vgmstream/vgmstream/releases) 下载 `vgmstream-mac.zip` 后把 `vgmstream-cli` 放进 PATH，或在 GUI 设置里指定路径
- Windows：从 [Releases](https://github.com/vgmstream/vgmstream/releases) 下载 `vgmstream-win64.zip`，在 GUI 设置里指定 `vgmstream-cli.exe` 路径

## 使用方法（图形界面，推荐）

1. Windows 双击 `start_studio.bat`（或运行 `python studio_gui.py`）；macOS 在仓库目录运行 `.venv/bin/python studio_gui.py`
2. 「游戏目录」一栏：
   - Windows：选择明日方舟 PC 客户端**根目录**（即包含 `Arknights_Data` 文件夹的那一层，通常是 `.../Arknights Game`）
   - macOS：**可留空**（自动检测 PlayCover 国服容器 `~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles`），或手动选择该 `Bundles` 目录

界面为暗色现代风格，分三个页签：

**BGM 快速替换** —— 选中音频点「替换 BGM」完事；「还原官方原版」一键换回。

**音频工坊** —— 替换任意音乐/语音/音效：
1. 点「刷新资源列表」：左侧按分类折叠展示（点击分类才加载内部资源，1700+ 资源秒开）；输入关键词（如 `amiya`、`act54side`）即时过滤为扁平结果，⌘F / Ctrl+F 快速聚焦过滤框
2. 选资源包（音乐 BGM / 干员语音 / 音效…），右侧自动加载包内全部 Clip
3. 选一条 Clip 可「试听」（支持拖拽进度、暂停/继续、停止）、「导出 WAV」
4. 底部选择你的音频，点「替换所选 Clip」（单 Clip 资源包可不选 Clip）

**Mod 管理** —— 查看全部已装 Mod 与实时状态（● 生效中 / ○ 已还原 / ⚠ 被更新覆盖）：逐个或全部还原、游戏更新后一键重新应用、打开备份目录。

## 使用方法（命令行）

```bash
# 现状总览 / 浏览资源（支持关键词过滤）
python studio.py --status
python studio.py --browse amiya

# 替换（wav/mp3/flac/m4a 皆可；--target/--clip 省略时默认替换扬升主界面 BGM）
python studio.py --apply "D:\music\某首歌.mp3" --target audio/sound_beta_2/music/act54side/m_sys_act54side_shop.ab
python studio.py --apply "语音.wav" --target audio/sound_beta_2/voice/char_002_amiya.ab --clip CN_001

# 导出游戏音频为 WAV（先看包内有哪些 clip）
python studio.py --extract audio/sound_beta_2/music/act54side/m_sys_act54side.ab
python studio.py --extract audio/sound_beta_2/voice/char_002_amiya.ab --clip CN_017 --out ~/Downloads/amiya.wav

# Mod 管理
python studio.py --mods                # 注册表与状态
python studio.py --restore <资源路径>  # 还原单个
python studio.py --restore-all         # 全部还原
python studio.py --reapply             # 游戏更新后一键重新应用被覆盖的 Mod
```

macOS 下把 `python` 换成 `.venv/bin/python`；`--game` 可省略（GUI 选过一次会记住，macOS 省略时自动检测 PlayCover 容器）。

## 音频格式要求

替换音频无需提前转换：直接选 **WAV / MP3 / FLAC / M4A**，工具自动处理。若手动准备 WAV，规格为 **44100 Hz / 16 bit / 单声道或立体声**。

时长没有限制（原版约 227 秒，你放三分钟的歌也没问题）。歌越好听，主界面越舍不得关。

注意：替换进游戏的音频一律以 PCM16 存储，替换 Vorbis 压缩的资源（大多数官方音乐/语音）后该 bundle 体积会明显增大，属正常现象，游戏可正常加载。

## 常见问题

**Q: 替换后游戏更新了怎么办？**
游戏更新会重新下载资源，替换会被覆盖。打开「Mod 管理」页签（或 `--mods`）会显示 ⚠ 被更新覆盖，点「重新应用被覆盖的」（或 `--reapply`）即可全部恢复——工具从当前文件取 CAB 模板，自动适配新版本结构。
如果重应用报「bundle 中未找到 AudioClip」或「bundle 结构与预期不符」，说明官方改了资源结构，等本工具适配。

**Q: 启动游戏报「资源加载异常」？**
先运行启动器的「完整性检查」把资源恢复为官方原版（此操作会清除替换），确认游戏能正常启动后，再重新替换。
网络状况差（代理/断网）时游戏的资源校验更容易失败，排查时注意先排除网络因素。

**Q: 试听/导出提示需要 vgmstream？**
官方音乐和语音大多是 Vorbis 压缩，解码它需要 vgmstream（见「安装」末尾）。替换功能本身不需要 vgmstream。已替换成 PCM 的资源可直接试听/导出。

**Q: 还原时报「备份不存在」？**
说明这个资源从未替换过。备份按原始路径保存在工具目录 `backup/files/` 下，别删。

**Q: macOS 下提示找不到游戏资源？**
需要先通过 PlayCover 完整进入过一次游戏（对应资源已下载），文件才会出现在 `.../Bundles/audio/...`。游戏刚更新时先进一次游戏让资源下载完成，再执行替换。

**Q: 会被封号吗？**
本工具不修改程序本体、不注入进程、不联网，只替换本地音频资源文件，与修改游戏内数值/破解有本质区别。
但任何本地修改都无法保证 100% 无风险，介意的请勿使用，用完记得还原。

## 工作原理（简述）

明日方舟的音频资源是 Unity AssetBundle，内含指向 FSB5 音频的 `AudioClip`（语音包等含多条，顺序拼接在 .resource 节点中）。本工具做的事：

1. 解析原 bundle（自定义解析器处理 LZ4AK 变体压缩，见 `akparse.py`）
2. 把你的音频封装成 PCM16 的 FSB5；多 Clip 包在原资源流中拼接替换并修正后续 Clip 偏移
3. 用 UnityPy 改写 AudioClip 元数据（时长、压缩格式、声道、资源大小/偏移）
4. 按原 bundle 的头部参数重新打包，并同步清单：Windows 更新 `hot_update_list.json` 的 md5/totalSize/abSize；macOS（iOS 端）条目同时登记在 `hot_update_list.json` 与 `persistent_res_list.json` 两份清单中，均只更新 md5/abSize（totalSize 为下载记账值、hash 为版本指纹，保持不动以免触发重下）
5. 每次替换登记到 `mods.json`（含官方原版/Mod 两份 md5），据此实现状态检测、还原与更新后重应用

更深入的技术细节（格式逐字段分析、FSB5 手工构建、重打包布局、macOS 适配）见 [TECH_DOC.md](TECH_DOC.md)。

## 免责声明

- 仅供本地学习、研究 Unity 资源格式之用，请支持官方游戏
- 使用本工具产生的一切后果（包括但不限于游戏损坏、需要重新下载资源）由使用者自行承担
- 与鹰角网络 / Hypergryph 无任何关联；「明日方舟」「Arknights」及相关名称归其权利人所有
- 再次提醒：**别分享。** 你自己知道这个地方就好。
