# -*- coding: utf-8 -*-
"""ArknightsModStudio (Tkinter GUI, Windows PC / macOS PlayCover)

明日方舟音频 Mod 工作台: BGM 快速替换 / 音频工坊 (浏览·试听·提取·替换) / Mod 管理
"""
import os
import sys
import json
import shutil
import threading
import traceback
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amslib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

IS_MAC = sys.platform == 'darwin'
FONT_UI  = ('PingFang SC', 12) if IS_MAC else ('Microsoft YaHei UI', 9)
FONT_MONO = ('Menlo', 11) if IS_MAC else ('Consolas', 9)

AUDIO_TYPES = [('音频文件', '*.wav *.mp3 *.flac *.m4a *.aiff *.aif'), ('所有文件', '*.*')]


def fmt_size(n):
    return '%.1f MB' % (n / 1048576) if n >= 1048576 else '%.0f KB' % (n / 1024)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ArknightsModStudio · 明日方舟音频 Mod 工作台')
        self.geometry('1020x680')
        self.minsize(860, 560)
        self.cfg = amslib.load_config()
        self._busy = False
        self._build()
        self.after(100, self.refresh_status)

    # ================= 界面骨架 =================
    def _build(self):
        # 顶部: 游戏目录
        frm_game = ttk.LabelFrame(
            self, text='游戏目录 (Windows: PC 客户端根目录 / macOS: PlayCover Bundles 目录, 可留空自动检测)', padding=6)
        frm_game.pack(fill='x', padx=12, pady=(10, 4))
        self.var_game = tk.StringVar(value=self.cfg.get('game_dir', ''))
        ttk.Entry(frm_game, textvariable=self.var_game).pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(frm_game, text='浏览...', width=10, command=self.on_pick_game).pack(side='left')

        # 中部: 三页签
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=12, pady=4)
        self.tab1 = ttk.Frame(nb, padding=10)
        self.tab2 = ttk.Frame(nb, padding=10)
        self.tab3 = ttk.Frame(nb, padding=10)
        nb.add(self.tab1, text='  BGM 快速替换  ')
        nb.add(self.tab2, text='  音频工坊  ')
        nb.add(self.tab3, text='  Mod 管理  ')
        nb.bind('<<NotebookTabChanged>>', lambda e: self.on_tab_changed(nb.index(nb.select())))
        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

        # 底部: 日志
        frm_log = ttk.LabelFrame(self, text='执行日志', padding=6)
        frm_log.pack(fill='both', padx=12, pady=(4, 10))
        sb = ttk.Scrollbar(frm_log)
        sb.pack(side='right', fill='y')
        self.txt = tk.Text(frm_log, height=9, font=FONT_MONO, state='disabled', yscrollcommand=sb.set)
        self.txt.pack(side='left', fill='both', expand=True)
        sb.config(command=self.txt.yview)

    # ---------- Tab 1: BGM 快速替换 ----------
    def _build_tab1(self):
        self.var_state = tk.StringVar(value='')
        ttk.Label(self.tab1, textvariable=self.var_state, font=FONT_UI).pack(anchor='w', pady=(0, 8))

        frm_wav = ttk.LabelFrame(self.tab1, text='替换音频 (WAV/MP3/FLAC/M4A, 非 WAV 自动转换为 44.1kHz/16bit/立体声)', padding=6)
        frm_wav.pack(fill='x')
        self.var_wav = tk.StringVar(value=self.cfg.get('last_audio', ''))
        ttk.Entry(frm_wav, textvariable=self.var_wav).pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(frm_wav, text='浏览...', width=10, command=self.on_pick_audio).pack(side='left')

        frm_btn = ttk.Frame(self.tab1)
        frm_btn.pack(fill='x', pady=10)
        self.btn_apply = ttk.Button(frm_btn, text='替换 BGM', command=self.on_apply_bgm)
        self.btn_apply.pack(side='left', expand=True, fill='x', padx=(0, 6))
        self.btn_restore = ttk.Button(frm_btn, text='还原官方原版', command=self.on_restore_bgm)
        self.btn_restore.pack(side='left', expand=True, fill='x', padx=(6, 0))

        tip = ('目标: 「扬升」主题主界面 BGM (Aria of the Soul)。要替换其他音乐/干员语音/音效, 请使用「音频工坊」页签。')
        ttk.Label(self.tab1, text=tip, foreground='#888').pack(anchor='w')

    # ---------- Tab 2: 音频工坊 ----------
    def _build_tab2(self):
        # 顶部过滤
        frm_top = ttk.Frame(self.tab2)
        frm_top.pack(fill='x', pady=(0, 6))
        ttk.Label(frm_top, text='过滤:').pack(side='left')
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add('write', lambda *_: self.apply_filter())
        ttk.Entry(frm_top, textvariable=self.var_filter, width=40).pack(side='left', padx=6)
        ttk.Button(frm_top, text='刷新资源列表', command=self.on_refresh_browser).pack(side='left', padx=6)
        self.var_browser_info = tk.StringVar(value='尚未加载 (点击「刷新资源列表」)')
        ttk.Label(frm_top, textvariable=self.var_browser_info, foreground='#888').pack(side='left', padx=10)

        # 中部: 左 bundle 树 / 右 clip 列表
        frm_mid = ttk.Frame(self.tab2)
        frm_mid.pack(fill='both', expand=True)
        frm_left = ttk.LabelFrame(frm_mid, text='资源包 (按分类)', padding=4)
        frm_left.pack(side='left', fill='both', expand=True, padx=(0, 6))
        sb1 = ttk.Scrollbar(frm_left)
        sb1.pack(side='right', fill='y')
        self.tree_res = ttk.Treeview(frm_left, columns=('size',), show='tree headings', yscrollcommand=sb1.set)
        self.tree_res.heading('#0', text='分类 / 资源')
        self.tree_res.heading('size', text='大小')
        self.tree_res.column('#0', width=420)
        self.tree_res.column('size', width=90, anchor='e')
        self.tree_res.pack(side='left', fill='both', expand=True)
        sb1.config(command=self.tree_res.yview)
        self.tree_res.bind('<<TreeviewSelect>>', lambda e: self.on_pick_bundle())

        frm_right = ttk.LabelFrame(frm_mid, text='包内 AudioClip (选中资源包后自动加载)', padding=4)
        frm_right.pack(side='left', fill='both', expand=True)
        sb2 = ttk.Scrollbar(frm_right)
        sb2.pack(side='right', fill='y')
        self.tree_clip = ttk.Treeview(
            frm_right, columns=('name', 'dur', 'fmt', 'size'), show='headings', yscrollcommand=sb2.set)
        for col, text, w, anchor in (('name', 'Clip', 260, 'w'), ('dur', '时长', 80, 'e'),
                                     ('fmt', '格式', 80, 'w'), ('size', '大小', 90, 'e')):
            self.tree_clip.heading(col, text=text)
            self.tree_clip.column(col, width=w, anchor=anchor)
        self.tree_clip.pack(side='left', fill='both', expand=True)
        sb2.config(command=self.tree_clip.yview)

        # clip 操作按钮
        frm_clipbtn = ttk.Frame(self.tab2)
        frm_clipbtn.pack(fill='x', pady=6)
        self.btn_play = ttk.Button(frm_clipbtn, text='试听', command=self.on_play_clip, state='disabled')
        self.btn_play.pack(side='left', padx=(0, 6))
        self.btn_export = ttk.Button(frm_clipbtn, text='导出 WAV', command=self.on_export_clip, state='disabled')
        self.btn_export.pack(side='left')
        self.var_vgm = tk.StringVar(
            value=self.cfg.get('vgmstream', '') or (amslib.find_vgmstream() or ''))
        self.var_vgm_info = tk.StringVar()
        self._update_vgm_info()
        ttk.Label(frm_clipbtn, textvariable=self.var_vgm_info, foreground='#888').pack(side='left', padx=12)
        ttk.Label(frm_clipbtn, text='vgmstream:').pack(side='right')
        ttk.Entry(frm_clipbtn, textvariable=self.var_vgm, width=42).pack(side='right', padx=4)
        self.var_vgm.trace_add('write', lambda *_: self._on_vgm_changed())

        # 替换区
        frm_apply = ttk.LabelFrame(self.tab2, text='替换为我的音频', padding=6)
        frm_apply.pack(fill='x')
        self.var_audio2 = tk.StringVar(value=self.cfg.get('last_audio', ''))
        ttk.Entry(frm_apply, textvariable=self.var_audio2).pack(
            side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(frm_apply, text='浏览...', width=10, command=self.on_pick_audio2).pack(side='left', padx=(0, 6))
        self.btn_apply2 = ttk.Button(frm_apply, text='替换所选 Clip', command=self.on_apply_clip, state='disabled')
        self.btn_apply2.pack(side='left')

        self._browser_rows = []            # browse_audio 结果缓存
        self._clip_cache = {}              # relpath -> clips

    # ---------- Tab 3: Mod 管理 ----------
    def _build_tab3(self):
        frm_btn = ttk.Frame(self.tab3)
        frm_btn.pack(fill='x', pady=(0, 6))
        for text, cmd in (('刷新状态', self.refresh_mods),
                          ('还原选中', self.on_restore_one),
                          ('全部还原', self.on_restore_all),
                          ('重新应用被覆盖的', self.on_reapply),
                          ('打开备份目录', self.on_open_backup)):
            ttk.Button(frm_btn, text=text, command=cmd).pack(side='left', padx=(0, 8))

        cols = (('status', '状态', 130), ('relpath', '资源', 420),
                ('clip', 'Clip', 200), ('applied', '应用时间', 140))
        self.tree_mod = ttk.Treeview(self.tab3, columns=[c[0] for c in cols], show='headings', height=12)
        for cid, text, w in cols:
            self.tree_mod.heading(cid, text=text)
            self.tree_mod.column(cid, width=w)
        self.tree_mod.pack(fill='both', expand=True)
        self.tree_mod.bind('<<TreeviewSelect>>', lambda e: self._sel_mod())
        self.lbl_mod_detail = tk.StringVar(value='选中 Mod 查看详情')
        ttk.Label(self.tab3, textvariable=self.lbl_mod_detail, foreground='#666').pack(anchor='w', pady=(6, 0))
        # 刷新按钮引用 (供线程结束后刷新)
        self.btn_mod_refresh = None

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
        self.btn_apply.config(state=state)
        self.btn_restore.config(state=state)
        self.btn_apply2.config(state=state if self._clip_selected() else 'disabled')

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
        if idx == 2:                     # Mod 管理
            self.refresh_mods()
        elif idx == 1 and not self._browser_rows:
            self.on_refresh_browser()

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
        except Exception:
            self.var_state.set('资源状态: 无法识别游戏目录')

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
        self.btn_play.config(state='normal' if self.tree_clip.get_children() else 'disabled')
        self.btn_export.config(state='normal' if self.tree_clip.get_children() else 'disabled')
        self.btn_apply2.config(state='normal' if self.tree_clip.get_children() else 'disabled')

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

    def on_play_clip(self):
        sel = self._selected_bundle_clip()
        if not sel:
            messagebox.showinfo('提示', '请先选择资源包和 Clip')
            return
        relpath, clip = sel

        def run():
            out = os.path.join(tempfile.gettempdir(), 'ams_preview_%s.wav' % abs(hash((relpath, clip))))
            amslib.extract_clip(self.var_game.get(), relpath, clip, out, vgmstream=self._vgm(), log=self.log)
            amslib.play_file(out)
        self.log('试听: %s / %s' % (relpath, clip))
        self._run_bg(run)

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
                m['clip'], m['applied_at']), tags=(m['relpath'],))

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
            import subprocess
            subprocess.Popen(['open', amslib.BACKUP_DIR])
        elif sys.platform == 'win32':
            os.startfile(amslib.BACKUP_DIR)


if __name__ == '__main__':
    amslib.migrate_legacy()
    App().mainloop()
