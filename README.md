# ak-bgm-swap

> **请勿分享、请勿传播。**
> 如果你找到这个仓库，就当是捡到的宝藏，自己偷偷用、偷偷享受就好。
> 转发到群里、贴吧、社交平台的瞬间，它离失效就不远了。

明日方舟「**扬升**」主题主界面 BGM 替换工具，支持 **Windows PC 客户端** 与 **macOS PlayCover（iOS 客户端）**。
把 `Aria of the Soul` 换成你喜欢的任意曲目，随时一键换回官方原版。

- 不改游戏程序，只替换一个音频资源包并同步校验清单
- 图形界面操作，替换 / 还原各一键完成
- 首次替换自动备份官方原版，随时可完整还原
- 本仓库**不含任何游戏资源、官方文件或音乐文件**，替换音频由使用者自备

## 环境要求

- Windows + 明日方舟 PC 官方客户端，或 macOS + PlayCover 运行的明日方舟（iOS 国服客户端，均测试于 2026-09 的 V077 版本，即「扬升」主题活动版本）
- Python 3.10 或更高（自带 Tkinter；macOS 用 Homebrew Python 时 tkinter 需另装 `python-tk`，见「安装」）

## 安装

```bash
git clone <本仓库地址>
cd ak-bgm-swap
pip install -r requirements.txt
```

不会用 git 的话：下载 ZIP 解压后，在文件夹里打开终端执行 `pip install -r requirements.txt`。

**macOS**（Homebrew Python 的 tkinter 是独立包，必须先装 `python-tk`）：

```bash
git clone <本仓库地址>
cd ak-bgm-swap
brew install python-tk@3.14          # 版本号对应 brew 安装的 python3 小版本
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用方法（图形界面，推荐）

1. Windows 双击 `start_gui.bat`（或运行 `python mod_gui.py`）；macOS 在仓库目录运行 `.venv/bin/python mod_gui.py`
2. 「游戏目录」一栏：
   - Windows：选择明日方舟 PC 客户端**根目录**（即包含 `Arknights_Data` 文件夹的那一层，通常是 `.../Arknights Game`）
   - macOS：**可留空**（自动检测 PlayCover 国服容器 `~/Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles`），或手动选择该 `Bundles` 目录
3. 「替换音频」一栏选择你想替换进去的 WAV 文件（格式要求见下）
4. 点击「替换 BGM」，等待日志出现“完成!”
5. 启动游戏，主界面切换到「扬升」主题即可听到新 BGM

想换回官方原版时：打开本工具点击「还原官方原版」即可。

## 使用方法（命令行）

```bash
# Windows
python modlib.py --game "F:\...\Arknights Game" --apply "D:\music\某首歌.wav"
python modlib.py --game "F:\...\Arknights Game" --restore
python modlib.py --game "F:\...\Arknights Game" --status

# macOS（--game 可省略，自动检测 PlayCover 容器）
.venv/bin/python modlib.py --apply "…/某首歌.wav"
.venv/bin/python modlib.py --restore
.venv/bin/python modlib.py --status
```

`--game` 也可省略：图形界面选过一次游戏目录后会记住（保存在 `config.json`）；macOS 下省略时自动检测 PlayCover 默认容器路径。

## 音频格式要求

替换文件必须是 **44100 Hz / 16 bit / 双声道（立体声）** 的 WAV。

其他格式一行转换（MP3/FLAC/OGG 均可）：

```bash
# Windows（ffmpeg）
ffmpeg -i "输入文件.mp3" -ar 44100 -sample_fmt s16 -ac 2 "输出.wav"

# macOS（系统自带 afconvert，无需 ffmpeg）
afconvert -f WAVE -d LEI16@44100 -c 2 "输入文件.mp3" "输出.wav"
```

时长没有限制（原版约 227 秒，你放三分钟的歌也没问题）。歌越好听，主界面越舍不得关。

## 常见问题

**Q: 替换后游戏更新了怎么办？**
游戏更新会重新下载资源，替换会被覆盖。更新完成后重新执行一次替换即可。
如果更新后工具报「CAB 中未找到 AudioClip」或「bundle 结构与预期不符」，说明官方改了资源结构，等本工具适配。

**Q: 启动游戏报「资源加载异常」？**
先运行启动器的「完整性检查」把资源恢复为官方原版（此操作会清除替换），确认游戏能正常启动后，再重新替换。
网络状况差（代理/断网）时游戏的资源校验更容易失败，排查时注意先排除网络因素。

**Q: 还原时报「备份不存在」？**
说明这个目录下从未执行过替换，无需还原。备份保存在工具目录的 `backup/` 文件夹里，别删。

**Q: macOS 下提示找不到游戏资源？**
需要先通过 PlayCover 完整进入过一次游戏（「扬升」主题的热更资源已下载），目标文件才会出现在 `.../Bundles/audio/sound_beta_2/music/act54side/`。游戏刚更新时先进一次游戏让资源下载完成，再执行替换。

**Q: 会被封号吗？**
本工具不修改程序本体、不注入进程、不联网，只替换本地音频资源文件，与修改游戏内数值/破解有本质区别。
但任何本地修改都无法保证 100% 无风险，介意的请勿使用，用完记得还原。

## 工作原理（简述）

明日方舟的音频资源是 Unity AssetBundle（`m_sys_act54side_mainpage.ab`），内含一个指向 FSB5 音频的 `AudioClip`。本工具做的事：

1. 解析原 bundle（自定义解析器处理 LZ4AK 变体压缩，见 `akparse.py`）
2. 把你的 WAV 封装成 PCM16 的 FSB5，替换 bundle 内的音频资源
3. 用 UnityPy 改写 AudioClip 元数据（时长、压缩格式、资源大小）
4. 按原 bundle 的头部参数重新打包，并同步清单：Windows 更新 `hot_update_list.json` 的 md5/totalSize/abSize；macOS（iOS 端）条目同时登记在 `hot_update_list.json` 与 `persistent_res_list.json` 两份清单中，均只更新 md5/abSize（totalSize 为下载记账值、hash 为版本指纹，保持不动以免触发重下）

更深入的技术细节（格式逐字段分析、FSB5 手工构建、重打包布局）见 [TECH_DOC.md](TECH_DOC.md)。

## 免责声明

- 仅供本地学习、研究 Unity 资源格式之用，请支持官方游戏
- 使用本工具产生的一切后果（包括但不限于游戏损坏、需要重新下载资源）由使用者自行承担
- 与鹰角网络 / Hypergryph 无任何关联；「明日方舟」「Arknights」及相关名称归其权利人所有
- 再次提醒：**别分享。** 你自己知道这个地方就好。
