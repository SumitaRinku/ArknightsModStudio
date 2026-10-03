# -*- coding: utf-8 -*-
"""ArknightsModStudio (CustomTkinter 现代化 GUI, Windows PC / macOS PlayCover)

明日方舟音频 Mod 工作台: BGM 快速替换 / 音频工坊 (浏览·试听·提取·替换) / Mod 管理
暗色主题: CustomTkinter 外壳 + 深色 ttk.Treeview 列表
"""
import os
import sys
import json
import shutil
import threading
import traceback
import tempfile
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amslib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

IS_MAC = sys.platform == 'darwin'
FONT_UI = ('PingFang SC', 13) if IS_MAC else ('Microsoft YaHei UI', 10)
FONT_UI_BOLD = (FONT_UI[0], FONT_UI[1], 'bold')
FONT_MONO = ('Menlo', 12) if IS_MAC else ('Consolas', 10)

AUDIO_TYPES = [('音频文件', '*.wav *.mp3 *.flac *.m4a *.aiff *.aif'), ('所有文件', '*.*')]

# ---- 配色 (暗色) ----
COL_CARD = '#2d2d2d'          # 卡片底
COL_CARD_DEEP = '#262626'     # 卡片内嵌区域 (列表底)
COL_TREE_HEAD = '#3a3a3a'     # 列表表头
COL_TREE_FG = '#e4e4e4'
COL_TREE_SEL = '#1f6aa5'
COL_MUTED = '#9a9a9a'          # 次要文字
COL_SUCCESS = '#4cc38a'
COL_WARN = '#f5a623'
COL_BTN_SUB = '#404040'        # 次级按钮
COL_BTN_SUB_HV = '#4e4e4e'

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')


def fmt_size(n):
    return '%.1f MB' % (n / 1048576) if n >= 1048576 else '%.0f KB' % (n / 1024)


def fmt_time(sec):
    m, s = divmod(max(0.0, float(sec or 0)), 60)
    return '%d:%04.1f' % (int(m), s)


def style_treeviews():
    """深色 ttk.Treeview 样式 (CTk 无树形组件, 用 ttk 补齐并配色)"""
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('AMS.Treeview', background=COL_CARD_DEEP, fieldbackground=COL_CARD_DEEP,
                    foreground=COL_TREE_FG, rowheight=30, borderwidth=0, font=FONT_UI)
    style.configure('AMS.Treeview.Heading', background=COL_TREE_HEAD, foreground=COL_MUTED,
                    relief='flat', font=FONT_UI_BOLD, padding=(6, 5))
    style.map('AMS.Treeview', background=[('selected', COL_TREE_SEL)],
              foreground=[('selected', '#ffffff')])
    style.map('AMS.Treeview.Heading', background=[('active', COL_TREE_HEAD)])


class Player:
    """试听播放控制。

    macOS 用 afplay 进程管理 (seek 用 WAV 切片实现), 支持进度/拖拽 seek/暂停/停止;
    其他平台回退系统播放器 (无进度控制, play() 返回 False)。
    """

    def __init__(self):
        self.proc = None
        self.path = None
        self.duration = 0.0
        self.start_off = 0.0
        self.t0 = 0.0
        self.paused_at = None
        self.no_control = False
        self._slice_path = None

    def _kill(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

    def _drop_slice(self):
        if self._slice_path:
            try:
                os.unlink(self._slice_path)
            except Exception:
                pass
            self._slice_path = None

    def stop(self):
        self._kill()
        self._drop_slice()
        self.path = None
        self.paused_at = None
        self.no_control = False

    def _read_duration(self, path):
        import wave
        try:
            with wave.open(path, 'rb') as w:
                rate = w.getframerate() or 44100
                self.duration = w.getnframes() / float(rate)
        except Exception:
            self.duration = 0.0

    @staticmethod
    def _slice_wav(path, offset):
        """截取 path 从 offset 秒开始的临时 WAV (afplay 无起播偏移参数, 用切片实现 seek)"""
        import wave
        fd, out = tempfile.mkstemp(suffix='.wav', prefix='ams_seek_')
        os.close(fd)
        with wave.open(path, 'rb') as r, wave.open(out, 'wb') as w:
            w.setnchannels(r.getnchannels())
            w.setsampwidth(r.getsampwidth())
            w.setframerate(r.getframerate())
            r.setpos(min(int(offset * r.getframerate()), r.getnframes()))
            while True:
                buf = r.readframes(65536)
                if not buf:
                    break
                w.writeframes(buf)
        return out

    def play(self, path, offset=0.0):
        """播放; 返回 True 表示可控 (支持进度条/暂停/seek)"""
        self._read_duration(path)
        self.path = path
        self.paused_at = None
        self.no_control = False
        if sys.platform == 'darwin':
            self._kill()
            self._drop_slice()
            self.start_off = max(0.0, min(offset, max(0.0, self.duration - 0.05)))
            src = path if self.start_off < 0.05 else self._slice_wav(path, self.start_off)
            if self.start_off >= 0.05:
                self._slice_path = src
            self.proc = subprocess.Popen(['afplay', src])
            self.t0 = time.monotonic()
            return True
        amslib.play_file(path)
        self.no_control = True
        return False

    def seek(self, offset):
        if self.path and not self.no_control:
            return self.play(self.path, offset)
        return False

    def pause(self):
        """暂停, 返回暂停位置; 非播放状态返回 None"""
        if self.playing:
            self.paused_at = self.position()
            self._kill()
            return self.paused_at
        return None

    def resume(self):
        if self.path and self.paused_at is not None and not self.no_control:
            off = self.paused_at
            self.paused_at = None
            return self.play(self.path, off)
        return False

    @property
    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def position(self):
        if not self.playing:
            return None
        return min(self.start_off + (time.monotonic() - self.t0), self.duration)


class App(ctk.CTk):
    TAB1, TAB2, TAB3 = 'BGM 快速替换', '音频工坊', 'Mod 管理'

    def __init__(self):
        super().__init__()
        self.title('ArknightsModStudio · 明日方舟音频 Mod 工作台')
        tk.Tk.geometry(self, '1120x880')     # 直接设置, 绕过 CTk 缩放
        self.minsize(960, 680)
        self.cfg = amslib.load_config()
        self._busy = False
        self.player = Player()
        self._seeking = False                 # 进度条拖拽中
        self._preview_files = {}              # (relpath, clip) -> 提取出的临时 wav
        self._last_tab = self.TAB1            # 页签变化检测 (CTkTabview.set 不触发 command)
        style_treeviews()
        self._build()
        self.after(100, self.refresh_status)
        self.after(200, self._tick_play)
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _on_close(self):
        try:
            self.player.stop()
        except Exception:
            pass
        self.destroy()

    # ================= 界面骨架 =================
    def _card(self, parent, title=None):
        """带圆角的卡片容器; 返回内容区 frame"""
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=COL_CARD)
        if title:
            ctk.CTkLabel(card, text=title, font=FONT_UI_BOLD, anchor='w').pack(
                fill='x', padx=14, pady=(8, 2))
        body = ctk.CTkFrame(card, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=12, pady=(4, 8))
        return card, body

    def _sub_button(self, parent, text, command, width=110):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=32,
                             corner_radius=8, fg_color=COL_BTN_SUB, hover_color=COL_BTN_SUB_HV)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(4, weight=0)

        # ---- 标题栏 ----
        head = ctk.CTkFrame(self, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', padx=18, pady=(12, 2))
        ctk.CTkLabel(head, text='ArknightsModStudio', font=(FONT_UI[0], 20, 'bold')).pack(side='left')
        ctk.CTkLabel(head, text='明日方舟音频 Mod 工作台', font=FONT_UI,
                     text_color=COL_MUTED).pack(side='left', padx=10, pady=(6, 0))

        # ---- 游戏目录 ----
        card, body = self._card(self, '游戏目录')
        card.grid(row=1, column=0, sticky='ew', padx=18, pady=(4, 4))
        self.var_game = tk.StringVar(value=self.cfg.get('game_dir', ''))
        ctk.CTkEntry(body, textvariable=self.var_game, height=32,
                     placeholder_text='Windows: PC 客户端根目录 · macOS: PlayCover Bundles 目录 (留空自动检测)'
                     ).pack(side='left', fill='x', expand=True, padx=(0, 8))
        ctk.CTkButton(body, text='浏览...', width=80, height=32, corner_radius=8,
                      fg_color=COL_BTN_SUB, hover_color=COL_BTN_SUB_HV,
                      command=self.on_pick_game).pack(side='left')

        # ---- 三页签 ----
        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.grid(row=2, column=0, sticky='nsew', padx=18, pady=6)
        self.tabview._segmented_button.configure(font=FONT_UI, height=36)
        for name in (self.TAB1, self.TAB2, self.TAB3):
            self.tabview.add(name)
        self.tab1 = self.tabview.tab(self.TAB1)
        self.tab2 = self.tabview.tab(self.TAB2)
        self.tab3 = self.tabview.tab(self.TAB3)
        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

        # ---- 日志 ----
        card, body = self._card(self, '执行日志')
        card.grid(row=3, column=0, sticky='ew', padx=18, pady=(2, 12))
        self.txt = tk.Text(body, height=3, font=FONT_MONO, state='disabled', relief='flat',
                           bg=COL_CARD_DEEP, fg=COL_TREE_FG, insertbackground=COL_TREE_FG,
                           padx=10, pady=8, selectbackground=COL_TREE_SEL, wrap='none',
                           highlightthickness=0, borderwidth=0)
        sb = ctk.CTkScrollbar(body, height=60, command=self.txt.yview, button_color='#4a4a4a')
        self.txt.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y', padx=(6, 0))
        self.txt.configure(yscrollcommand=sb.set)

    def _on_tabview_changed(self, *_):
        cur = self.tabview.get()
        if cur == self.TAB3:
            self.refresh_mods()
        elif cur == self.TAB2 and not self._browser_rows:
            self.on_refresh_browser()

    # ---------- Tab 1: BGM 快速替换 ----------
    def _build_tab1(self):
        self.var_state = tk.StringVar(value='')
        self.lbl_state = ctk.CTkLabel(self.tab1, textvariable=self.var_state,
                                      font=(FONT_UI[0], FONT_UI[1] + 2, 'bold'))
        self.lbl_state.pack(anchor='w', padx=4, pady=(4, 8))

        card, body = self._card(self.tab1, '替换音频')
        card.pack(fill='x', pady=(0, 8))
        ctk.CTkLabel(body, text='WAV / MP3 / FLAC / M4A, 非 WAV 自动转换为 44.1kHz / 16bit / 立体声',
                     font=FONT_UI, text_color=COL_MUTED, anchor='w').pack(fill='x')
        row = ctk.CTkFrame(body, fg_color='transparent')
        row.pack(fill='x', pady=(6, 0))
        self.var_wav = tk.StringVar(value=self.cfg.get('last_audio', ''))
        ctk.CTkEntry(row, textvariable=self.var_wav, height=32,
                     placeholder_text='选择你的音频文件...').pack(
            side='left', fill='x', expand=True, padx=(0, 8))
        ctk.CTkButton(row, text='浏览...', width=80, height=32, corner_radius=8,
                      fg_color=COL_BTN_SUB, hover_color=COL_BTN_SUB_HV,
                      command=self.on_pick_audio).pack(side='left')

        frm_btn = ctk.CTkFrame(self.tab1, fg_color='transparent')
        frm_btn.pack(fill='x', pady=4)
        self.btn_apply = ctk.CTkButton(frm_btn, text='替换 BGM', height=40, corner_radius=10,
                                       font=FONT_UI_BOLD, command=self.on_apply_bgm)
        self.btn_apply.pack(side='left', expand=True, fill='x', padx=(0, 8))
        self.btn_restore = ctk.CTkButton(frm_btn, text='还原官方原版', height=40, corner_radius=10,
                                         font=FONT_UI_BOLD, fg_color=COL_BTN_SUB,
                                         hover_color=COL_BTN_SUB_HV, command=self.on_restore_bgm)
        self.btn_restore.pack(side='left', expand=True, fill='x', padx=(8, 0))

        ctk.CTkLabel(self.tab1,
                     text='目标: 「扬升」主题主界面 BGM (Aria of the Soul)。要替换其他音乐 / 干员语音 / 音效, 请使用「音频工坊」页签。',
                     font=FONT_UI, text_color=COL_MUTED, anchor='w', justify='left').pack(
            anchor='w', padx=4, pady=(4, 0))

    # ---------- Tab 2: 音频工坊 ----------
    def _build_tab2(self):
        # 顶部过滤
        frm_top = ctk.CTkFrame(self.tab2, fg_color='transparent')
        frm_top.pack(fill='x', pady=(0, 6))
        ctk.CTkLabel(frm_top, text='过滤', font=FONT_UI, text_color=COL_MUTED).pack(side='left')
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add('write', lambda *_: self.apply_filter())
        ctk.CTkEntry(frm_top, textvariable=self.var_filter, width=260, height=32,
                     placeholder_text='关键词, 如 amiya / act54side').pack(side='left', padx=8)
        ctk.CTkButton(frm_top, text='刷新资源列表', width=110, height=32, corner_radius=8,
                      fg_color=COL_BTN_SUB, hover_color=COL_BTN_SUB_HV,
                      command=self.on_refresh_browser).pack(side='left', padx=(0, 12))
        self.var_browser_info = tk.StringVar(value='尚未加载 (点击「刷新资源列表」)')
        ctk.CTkLabel(frm_top, textvariable=self.var_browser_info, font=FONT_UI,
                     text_color=COL_MUTED).pack(side='left')

        # 中部: 左 bundle 树 / 右 clip 列表
        frm_mid = ctk.CTkFrame(self.tab2, fg_color='transparent')
        frm_mid.pack(fill='both', expand=True)
        frm_mid.grid_columnconfigure(0, weight=5)
        frm_mid.grid_columnconfigure(1, weight=6)
        frm_mid.grid_rowconfigure(0, weight=1)

        card_l, body_l = self._card(frm_mid, '资源包 (按分类)')
        card_l.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        sb1 = ctk.CTkScrollbar(body_l, height=60, command=None, button_color='#4a4a4a')
        self.tree_res = ttk.Treeview(body_l, style='AMS.Treeview', columns=('size',),
                                     show='tree headings', height=2, yscrollcommand=sb1.set)
        sb1.configure(command=self.tree_res.yview)
        self.tree_res.pack(side='left', fill='both', expand=True)
        sb1.pack(side='right', fill='y', padx=(6, 0))
        self.tree_res.heading('#0', text='分类 / 资源')
        self.tree_res.heading('size', text='大小')
        self.tree_res.column('#0', width=400)
        self.tree_res.column('size', width=90, anchor='e')
        self.tree_res.bind('<<TreeviewSelect>>', lambda e: self.on_pick_bundle())

        card_r, body_r = self._card(frm_mid, '包内 AudioClip (选中资源包后自动加载)')
        card_r.grid(row=0, column=1, sticky='nsew')
        sb2 = ctk.CTkScrollbar(body_r, height=60, command=None, button_color='#4a4a4a')
        self.tree_clip = ttk.Treeview(body_r, style='AMS.Treeview', height=2,
                                      columns=('name', 'dur', 'fmt', 'size'), show='headings',
                                      yscrollcommand=sb2.set)
        sb2.configure(command=self.tree_clip.yview)
        self.tree_clip.pack(side='left', fill='both', expand=True)
        sb2.pack(side='right', fill='y', padx=(6, 0))
        for col, text, w, anchor in (('name', 'Clip', 250, 'w'), ('dur', '时长', 80, 'e'),
                                     ('fmt', '格式', 80, 'w'), ('size', '大小', 90, 'e')):
            self.tree_clip.heading(col, text=text)
            self.tree_clip.column(col, width=w, anchor=anchor)

        # clip 操作按钮 + vgmstream 设置
        frm_clipbtn = ctk.CTkFrame(self.tab2, fg_color='transparent')
        frm_clipbtn.pack(fill='x', pady=(8, 2))
        self.btn_play = self._sub_button(frm_clipbtn, '试听', self.on_play_clip)
        self.btn_play.configure(state='disabled')
        self.btn_play.pack(side='left', padx=(0, 8))
        self.btn_export = self._sub_button(frm_clipbtn, '导出 WAV', self.on_export_clip)
        self.btn_export.configure(state='disabled')
        self.btn_export.pack(side='left')
        self.var_vgm = tk.StringVar(
            value=self.cfg.get('vgmstream', '') or (amslib.find_vgmstream() or ''))
        self.var_vgm_info = tk.StringVar()
        self.lbl_vgm_info = ctk.CTkLabel(frm_clipbtn, textvariable=self.var_vgm_info,
                                         font=FONT_UI, text_color=COL_MUTED)
        self.lbl_vgm_info.pack(side='left', padx=14)
        ctk.CTkEntry(frm_clipbtn, textvariable=self.var_vgm, width=300, height=30,
                     placeholder_text='vgmstream-cli 路径 (可选)').pack(side='right', padx=(6, 0))
        ctk.CTkLabel(frm_clipbtn, text='vgmstream', font=FONT_UI,
                     text_color=COL_MUTED).pack(side='right')
        self.var_vgm.trace_add('write', lambda *_: self._on_vgm_changed())
        self._update_vgm_info()

        # 试听播放 + 替换 (合并卡片: 第一行播放控制, 第二行替换)
        card, body = self._card(self.tab2, '试听播放 · 替换')
        card.pack(fill='x', pady=(6, 0))
        row1 = ctk.CTkFrame(body, fg_color='transparent')
        row1.pack(fill='x')
        self.btn_stop = self._sub_button(row1, '停止', self.on_stop_play, width=70)
        self.btn_stop.configure(state='disabled')
        self.btn_stop.pack(side='left', padx=(0, 6))
        self.btn_pause = self._sub_button(row1, '暂停', self.on_pause_play, width=70)
        self.btn_pause.configure(state='disabled')
        self.btn_pause.pack(side='left', padx=(0, 12))
        self.scale_pos = ctk.CTkSlider(row1, from_=0, to=100, height=22,
                                       progress_color=COL_TREE_SEL, command=self._on_slide)
        self.scale_pos.pack(side='left', fill='x', expand=True)
        self.scale_pos.bind('<Button-1>', lambda e: setattr(self, '_seeking', True))
        self.scale_pos.bind('<ButtonRelease-1>', self._on_scale_release)
        self.var_time = tk.StringVar(value='0:00.0 / 0:00.0')
        ctk.CTkLabel(row1, textvariable=self.var_time, font=FONT_MONO, width=120,
                     anchor='e').pack(side='left', padx=(12, 0))

        row2 = ctk.CTkFrame(body, fg_color='transparent')
        row2.pack(fill='x', pady=(8, 0))
        self.var_audio2 = tk.StringVar(value=self.cfg.get('last_audio', ''))
        ctk.CTkEntry(row2, textvariable=self.var_audio2, height=32,
                     placeholder_text='替换为我的音频 (WAV/MP3/FLAC/M4A)...').pack(
            side='left', fill='x', expand=True, padx=(0, 8))
        ctk.CTkButton(row2, text='浏览...', width=80, height=32, corner_radius=8,
                      fg_color=COL_BTN_SUB, hover_color=COL_BTN_SUB_HV,
                      command=self.on_pick_audio2).pack(side='left', padx=(0, 8))
        self.btn_apply2 = ctk.CTkButton(row2, text='替换所选 Clip', height=32, corner_radius=8,
                                        font=FONT_UI_BOLD, command=self.on_apply_clip)
        self.btn_apply2.configure(state='disabled')
        self.btn_apply2.pack(side='left')

        self._browser_rows = []            # browse_audio 结果缓存
        self._clip_cache = {}              # relpath -> clips

    # ---------- Tab 3: Mod 管理 ----------
    def _build_tab3(self):
        frm_btn = ctk.CTkFrame(self.tab3, fg_color='transparent')
        frm_btn.pack(fill='x', pady=(0, 8))
        for text, cmd in (('刷新状态', self.refresh_mods),
                          ('还原选中', self.on_restore_one),
                          ('全部还原', self.on_restore_all),
                          ('重新应用被覆盖的', self.on_reapply),
                          ('打开备份目录', self.on_open_backup)):
            self._sub_button(frm_btn, text, cmd, width=max(90, 24 * len(text))).pack(
                side='left', padx=(0, 8))

        card, body = self._card(self.tab3)
        card.pack(fill='both', expand=True)
        cols = (('status', '状态', 130), ('relpath', '资源', 420),
                ('clip', 'Clip', 200), ('applied', '应用时间', 140))
        sb3 = ctk.CTkScrollbar(body, height=60, command=None, button_color='#4a4a4a')
        self.tree_mod = ttk.Treeview(body, style='AMS.Treeview', height=2,
                                     columns=[c[0] for c in cols], show='headings',
                                     yscrollcommand=sb3.set)
        sb3.configure(command=self.tree_mod.yview)
        self.tree_mod.pack(side='left', fill='both', expand=True)
        sb3.pack(side='right', fill='y', padx=(6, 0))
        for cid, text, w in cols:
            self.tree_mod.heading(cid, text=text)
            self.tree_mod.column(cid, width=w)
        self.tree_mod.bind('<<TreeviewSelect>>', lambda e: self._sel_mod())
        # 状态着色
        self.tree_mod.tag_configure('active', foreground=COL_SUCCESS)
        self.tree_mod.tag_configure('official', foreground=COL_MUTED)
        self.tree_mod.tag_configure('overwritten', foreground=COL_WARN)
        self.lbl_mod_detail = tk.StringVar(value='选中 Mod 查看详情')
        ctk.CTkLabel(self.tab3, textvariable=self.lbl_mod_detail, font=FONT_UI,
                     text_color=COL_MUTED, anchor='w').pack(anchor='w', padx=4, pady=(6, 0))

    # ================= 通用 =================
    def log(self, msg):
        self.txt.config(state='normal')
        self.txt.insert('end', msg + '\n')
        self.txt.see('end')
        self.txt.config(state='disabled')

    def _run_bg(self, fn, done=None):
        """后台线程执行 amslib 操作, 防止界面卡死"""
        def worker():
            self._busy = True
            self._set_buttons('disabled')
            try:
                fn()
                err = None
            except Exception:
                self.log(traceback.format_exc())
                err = True
            self._busy = False
            self.after(0, lambda: self._set_buttons('normal'))
            self.after(0, self.refresh_status)
            self.after(0, self.refresh_mods)
            if done:
                self.after(0, lambda: done(err))
        threading.Thread(target=worker, daemon=True).start()

    def _set_buttons(self, state):
        self.btn_apply.configure(state=state)
        self.btn_restore.configure(state=state)
        self.btn_apply2.configure(state=state if self._clip_selected() else 'disabled')

    def _clip_selected(self):
        return bool(self.tree_clip.selection())

    def on_pick_game(self):
        d = filedialog.askdirectory(title='选择游戏目录 (Windows: 客户端根目录 / macOS: Bundles 热更目录)')
        if d:
            self.var_game.set(os.path.normpath(d))
            self.cfg['game_dir'] = self.var_game.get()
            amslib.save_config(self.cfg)
            self.refresh_status()
            self.on_refresh_browser()

    def on_tab_changed(self, idx):
        """兼容旧索引式切换"""
        self.tabview.set((self.TAB1, self.TAB2, self.TAB3)[idx])

    # ================= Tab1 逻辑 =================
    def on_pick_audio(self):
        p = filedialog.askopenfilename(title='选择音频文件 (WAV/MP3/FLAC/M4A)', filetypes=AUDIO_TYPES)
        if p:
            self.var_wav.set(p)
            self.var_audio2.set(p)
            self.cfg['last_audio'] = p
            amslib.save_config(self.cfg)

    def on_pick_audio2(self):
        p = filedialog.askopenfilename(title='选择音频文件 (WAV/MP3/FLAC/M4A)', filetypes=AUDIO_TYPES)
        if p:
            self.var_audio2.set(p)
            self.var_wav.set(p)
            self.cfg['last_audio'] = p
            amslib.save_config(self.cfg)

    def refresh_status(self):
        try:
            st = amslib.current_state(self.var_game.get())
            self.var_state.set('资源状态: ' + st[0])
            color = COL_SUCCESS if '已替换' in st[0] else COL_MUTED
            self.lbl_state.configure(text_color=color)
        except Exception:
            self.var_state.set('资源状态: 无法识别游戏目录')
            self.lbl_state.configure(text_color=COL_WARN)

    def on_apply_bgm(self):
        audio = self.var_wav.get().strip()
        if not audio or not os.path.exists(audio):
            messagebox.showerror('错误', '请先选择有效的音频文件')
            return
        self.log('==== 替换「扬升」主界面 BGM: %s ====' % os.path.basename(audio))
        self._run_bg(lambda: amslib.apply_mod(self.var_game.get(), audio, log=self.log),
                     done=lambda err: None if err else messagebox.showinfo('完成', '替换成功! 启动游戏即可生效。'))

    def on_restore_bgm(self):
        self.log('==== 还原「扬升」主界面 BGM 为官方原版 ====')
        self._run_bg(lambda: amslib.restore_mod(self.var_game.get(), amslib.DEFAULT_ENTRY, log=self.log))

    # ================= Tab2 逻辑 =================
    def on_refresh_browser(self):
        def load():
            try:
                rows = amslib.browse_audio(self.var_game.get())
                self.after(0, lambda: self._fill_browser(rows))
            except Exception:
                self.log(traceback.format_exc())
                self.after(0, lambda: self.var_browser_info.set('加载失败, 见日志'))
        self.var_browser_info.set('加载中...')
        threading.Thread(target=load, daemon=True).start()

    def _fill_browser(self, rows):
        self._browser_rows = rows
        self._clip_cache.clear()
        self.apply_filter()

    def apply_filter(self):
        kw = self.var_filter.get().strip().lower()
        self.tree_res.delete(*self.tree_res.get_children(''))
        self.tree_clip.delete(*self.tree_clip.get_children(''))
        cats = {}
        for cat, relpath, size in self._browser_rows:
            if kw and kw not in relpath.lower():
                continue
            cats.setdefault(cat, []).append((relpath, size))
        for cat, items in cats.items():
            node = self.tree_res.insert('', 'end', text='%s (%d)' % (cat, len(items)), open=False,
                                        values=('',))
            for relpath, size in items:
                short = relpath.split('audio/sound_beta_2/', 1)[-1]
                self.tree_res.insert(node, 'end', text=short, values=(fmt_size(size),),
                                     tags=(relpath,))
        self.var_browser_info.set('共 %d 个资源包' % sum(len(v) for v in cats.values()))

    def on_pick_bundle(self):
        sel = self.tree_res.selection()
        if not sel:
            return
        tags = self.tree_res.item(sel[0], 'tags')
        if not tags:                     # 分类节点
            return
        relpath = tags[0]

        def load():
            try:
                clips = amslib.list_audio_clips(amslib._require_ab(amslib.resolve_game(self.var_game.get()), relpath))
                self._clip_cache[relpath] = clips
                self.after(0, lambda: self._fill_clips(relpath))
            except Exception:
                self.log(traceback.format_exc())
        self.tree_clip.delete(*self.tree_clip.get_children(''))
        self.tree_clip.insert('', 'end', values=('加载中...', '', '', ''))
        threading.Thread(target=load, daemon=True).start()

    def _fill_clips(self, relpath):
        if not self.tree_res.selection():
            return
        cur = self.tree_res.item(self.tree_res.selection()[0], 'tags')
        if not cur or cur[0] != relpath:
            return
        self.tree_clip.delete(*self.tree_clip.get_children(''))
        for c in self._clip_cache.get(relpath, []):
            self.tree_clip.insert('', 'end', values=(
                c['name'], '%.1fs' % c['length'],
                amslib.FMT_NAMES.get(c['fmt'], str(c['fmt'])), fmt_size(c['size'])))
        state = 'normal' if self.tree_clip.get_children() else 'disabled'
        self.btn_play.configure(state=state)
        self.btn_export.configure(state=state)
        self.btn_apply2.configure(state=state)

    def _selected_bundle_clip(self):
        """返回 (relpath, clip名) 或 None"""
        sel = self.tree_res.selection()
        if not sel:
            return None
        tags = self.tree_res.item(sel[0], 'tags')
        if not tags:
            return None
        relpath = tags[0]
        csel = self.tree_clip.selection()
        if csel:
            return relpath, self.tree_clip.item(csel[0], 'values')[0]
        clips = self._clip_cache.get(relpath)
        if clips and len(clips) == 1:
            return relpath, clips[0]['name']
        return None

    def _vgm(self):
        p = self.var_vgm.get().strip()
        return p if p and os.path.isfile(p) else (amslib.find_vgmstream(self.cfg) or None)

    def _on_vgm_changed(self):
        self.cfg['vgmstream'] = self.var_vgm.get().strip()
        amslib.save_config(self.cfg)
        self._update_vgm_info()

    def _update_vgm_info(self):
        ok = self._vgm()
        self.var_vgm_info.set('(Vorbis 试听/导出: %s)' % ('可用 ✓' if ok else '不可用, Vorbis 无法导出'))
        self.lbl_vgm_info.configure(text_color=COL_SUCCESS if ok else COL_WARN)

    def on_play_clip(self):
        sel = self._selected_bundle_clip()
        if not sel:
            messagebox.showinfo('提示', '请先选择资源包和 Clip')
            return
        relpath, clip = sel
        key = (relpath, clip)
        cached = self._preview_files.get(key)
        if cached and os.path.exists(cached):
            self.log('试听 (缓存): %s / %s' % (relpath, clip))
            self._start_preview(cached)
            return
        out = os.path.join(tempfile.gettempdir(), 'ams_preview_%s.wav' % abs(hash(key)))
        self.btn_play.configure(state='disabled')
        self.var_time.set('提取中...')

        def run():
            amslib.extract_clip(self.var_game.get(), relpath, clip, out, vgmstream=self._vgm(), log=self.log)

        def done(err):
            self.btn_play.configure(state='normal')
            if not err:
                self._preview_files[key] = out
                self._start_preview(out)
            else:
                self.var_time.set('提取失败')
        self.log('试听: %s / %s' % (relpath, clip))
        self._run_bg(run, done=done)

    # ---------- 试听播放控制 ----------
    def _start_preview(self, path):
        try:
            ok = self.player.play(path, 0.0)
        except Exception:
            self.log(traceback.format_exc())
            self.var_time.set('播放失败')
            return
        if ok:
            self.btn_stop.configure(state='normal')
            self.btn_pause.configure(state='normal', text='暂停')
            self.scale_pos.configure(to=max(0.1, self.player.duration))
            self.scale_pos.set(0)
            self._update_time(0)
        else:
            self.var_time.set('系统播放器已打开')

    def on_stop_play(self):
        self.player.stop()
        self._play_ui_reset()

    def on_pause_play(self):
        p = self.player
        if p.paused_at is not None:             # 暂停 -> 继续
            if p.resume():
                self.btn_pause.configure(text='暂停')
        elif p.playing:                          # 播放 -> 暂停
            pos = p.pause()
            self.btn_pause.configure(text='继续')
            if pos is not None:
                self._update_time(pos)

    def _on_slide(self, val):
        """拖动滑块过程中的实时时间预览"""
        if self._seeking and self.player.path is not None:
            self._update_time(min(float(val), self.player.duration))

    def _on_scale_release(self, _e=None):
        self._seeking = False
        p = self.player
        if p.path is None or p.no_control:
            return
        pos = max(0.0, min(self.scale_pos.get(), p.duration))
        if p.paused_at is not None:              # 暂停中: 只改续播点
            p.paused_at = pos
            self._update_time(pos)
        else:                                    # 播放中: 立即跳转
            p.seek(pos)

    def _tick_play(self):
        try:
            cur = self.tabview.get()
            if cur != self._last_tab:            # 页签切换检测 (点击/程序切换均覆盖)
                self._last_tab = cur
                self._on_tabview_changed()
            p = self.player
            if p.playing:
                pos = p.position()
                if not self._seeking:
                    self.scale_pos.set(pos)
                self._update_time(pos)
            elif p.path is not None and p.paused_at is None and not p.no_control:
                p.stop()                         # 自然播完
                self._play_ui_reset()
        finally:
            self.after(200, self._tick_play)

    def _update_time(self, pos):
        self.var_time.set('%s / %s' % (fmt_time(pos), fmt_time(self.player.duration)))

    def _play_ui_reset(self):
        self.btn_stop.configure(state='disabled')
        self.btn_pause.configure(state='disabled', text='暂停')
        self.scale_pos.set(0)
        self.var_time.set('0:00.0 / 0:00.0')

    def on_export_clip(self):
        sel = self._selected_bundle_clip()
        if not sel:
            messagebox.showinfo('提示', '请先选择资源包和 Clip')
            return
        relpath, clip = sel
        out = filedialog.asksaveasfilename(title='导出 WAV', defaultextension='.wav',
                                           initialfile=clip + '.wav',
                                           filetypes=[('WAV 音频', '*.wav')])
        if not out:
            return

        def run():
            amslib.extract_clip(self.var_game.get(), relpath, clip, out, vgmstream=self._vgm(), log=self.log)
        self.log('导出: %s / %s -> %s' % (relpath, clip, out))
        self._run_bg(run, done=lambda err: None if err else messagebox.showinfo('完成', '已导出:\n' + out))

    def on_apply_clip(self):
        sel = self._selected_bundle_clip()
        if not sel:
            messagebox.showinfo('提示', '请先选择资源包和 Clip\n(单 Clip 资源包可不选 Clip)')
            return
        audio = self.var_audio2.get().strip()
        if not audio or not os.path.exists(audio):
            messagebox.showerror('错误', '请先选择有效的音频文件')
            return
        relpath, clip = sel
        self.log('==== 替换 %s 的 clip「%s」 ====' % (relpath, clip))
        self._run_bg(lambda: amslib.apply_mod(self.var_game.get(), audio, relpath=relpath, clip=clip, log=self.log),
                     done=lambda err: None if err else messagebox.showinfo('完成', '替换成功! 启动游戏即可生效。'))

    # ================= Tab3 逻辑 =================
    def refresh_mods(self):
        try:
            mods = amslib.list_mods(self.var_game.get())
        except Exception:
            return
        self.tree_mod.delete(*self.tree_mod.get_children(''))
        for m in mods:
            self.tree_mod.insert('', 'end', values=(
                amslib.STATUS_TEXT.get(m['status'], m['status']), m['relpath'],
                m['clip'], m['applied_at']), tags=(m['relpath'], m['status']))

    def _sel_mod(self):
        sel = self.tree_mod.selection()
        if not sel:
            return
        relpath = self.tree_mod.item(sel[0], 'tags')[0]
        mods = amslib.load_mods()
        ent = mods.get(relpath, {})
        self.lbl_mod_detail.set('源音频: %s' % (ent.get('source_audio') or '(未知)'))

    def on_restore_one(self):
        sel = self.tree_mod.selection()
        if not sel:
            messagebox.showinfo('提示', '请先在列表中选择一个 Mod')
            return
        relpath = self.tree_mod.item(sel[0], 'tags')[0]
        self.log('==== 还原: %s ====' % relpath)
        self._run_bg(lambda: amslib.restore_mod(self.var_game.get(), relpath, log=self.log))

    def on_restore_all(self):
        if not amslib.load_mods():
            messagebox.showinfo('提示', '注册表为空')
            return
        self.log('==== 全部还原 ====')
        self._run_bg(lambda: amslib.restore_all(self.var_game.get(), log=self.log))

    def on_reapply(self):
        self.log('==== 重新应用被覆盖的 Mod ====')
        self._run_bg(lambda: amslib.reapply_all(self.var_game.get(), log=self.log))

    def on_open_backup(self):
        os.makedirs(amslib.FILES_DIR, exist_ok=True)
        if IS_MAC:
            subprocess.Popen(['open', amslib.BACKUP_DIR])
        elif sys.platform == 'win32':
            os.startfile(amslib.BACKUP_DIR)


if __name__ == '__main__':
    amslib.migrate_legacy()
    App().mainloop()
