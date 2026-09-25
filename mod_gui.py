# -*- coding: utf-8 -*-
"""明日方舟「扬升」主题主界面 BGM 切换器 (Tkinter GUI, 可移植版)"""
import os
import sys
import json
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


def load_config():
    if os.path.exists(CONFIG):
        try:
            return json.load(open(CONFIG, encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_config(cfg):
    with open(CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('明日方舟 · 扬升主题 BGM 切换器')
        self.resizable(False, False)
        self.cfg = load_config()
        self._build()

    # ---------- 界面 ----------
    def _build(self):
        pad = dict(pady=4)

        # 游戏目录
        frm_game = ttk.LabelFrame(self, text='游戏目录 (明日方舟 PC 客户端根目录)', padding=6)
        frm_game.pack(fill='x', padx=14, pady=(10, 2))
        self.var_game = tk.StringVar(value=self.cfg.get('game_dir', ''))
        ttk.Entry(frm_game, textvariable=self.var_game).pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(frm_game, text='浏览...', width=10, command=self.on_pick_game).pack(side='left')

        # WAV 选择
        frm_wav = ttk.LabelFrame(self, text='替换音频 (44.1kHz / 16bit / 立体声 WAV)', padding=6)
        frm_wav.pack(fill='x', padx=14, **pad)
        self.var_wav = tk.StringVar(value=self.cfg.get('last_wav', ''))
        self.ent_wav = ttk.Entry(frm_wav, textvariable=self.var_wav)
        self.ent_wav.pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(frm_wav, text='浏览...', width=10, command=self.on_pick_wav).pack(side='left')

        # 状态行
        self.var_status = tk.StringVar(value='')
        frm_status = ttk.Frame(self)
        frm_status.pack(fill='x', padx=14, **pad)
        ttk.Label(frm_status, textvariable=self.var_status,
                  font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w')

        # 按钮区
        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill='x', padx=14, **pad)
        self.btn_apply = ttk.Button(frm_btn, text='替换 BGM', command=self.on_apply)
        self.btn_apply.pack(side='left', expand=True, fill='x', padx=(0, 6))
        self.btn_restore = ttk.Button(frm_btn, text='还原官方原版', command=self.on_restore)
        self.btn_restore.pack(side='left', expand=True, fill='x', padx=(6, 0))

        # 状态输出
        frm_log = ttk.LabelFrame(self, text='执行日志', padding=6)
        frm_log.pack(fill='both', expand=True, padx=14, pady=(4, 12))
        sb = ttk.Scrollbar(frm_log)
        sb.pack(side='right', fill='y')
        self.txt = tk.Text(frm_log, height=10, width=78, font=('Consolas', 9),
                           state='disabled', yscrollcommand=sb.set)
        self.txt.pack(side='left', fill='both', expand=True)
        sb.config(command=self.txt.yview)

        self.after(100, self.refresh_status)

    def log(self, msg):
        self.txt.config(state='normal')
        self.txt.insert('end', msg + '\n')
        self.txt.see('end')
        self.txt.config(state='disabled')
        self.update_idletasks()

    # ---------- 事件 ----------
    def on_pick_game(self):
        d = filedialog.askdirectory(title='选择明日方舟 PC 客户端根目录')
        if d:
            self.var_game.set(os.path.normpath(d))
            self.cfg['game_dir'] = self.var_game.get()
            save_config(self.cfg)
            self.refresh_status()

    def on_pick_wav(self):
        p = filedialog.askopenfilename(title='选择 WAV 文件',
                                       filetypes=[('WAV 音频', '*.wav'), ('所有文件', '*.*')])
        if p:
            self.var_wav.set(p)
            self.cfg['last_wav'] = p
            save_config(self.cfg)

    def refresh_status(self):
        try:
            state, _ = modlib.current_state(self.var_game.get())
            self.var_status.set('资源状态: ' + state)
        except Exception as e:
            self.var_status.set('资源状态: 无法识别游戏目录')

    def _run_bg(self, fn):
        def worker():
            self.btn_apply.config(state='disabled')
            self.btn_restore.config(state='disabled')
            try:
                fn()
            except Exception:
                self.log(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror('失败', '操作失败, 详情见日志'))
            else:
                self.after(0, lambda: messagebox.showinfo('完成', '操作成功!'))
            finally:
                self.btn_apply.config(state='normal')
                self.btn_restore.config(state='normal')
                self.after(0, self.refresh_status)
        threading.Thread(target=worker, daemon=True).start()

    def on_apply(self):
        game = self.var_game.get().strip()
        wav = self.var_wav.get().strip()
        if not game:
            messagebox.showerror('错误', '请先选择游戏根目录')
            return
        if not wav or not os.path.exists(wav):
            messagebox.showerror('错误', '请先选择有效的 WAV 文件')
            return
        self.log('==== 替换为: %s ====' % os.path.basename(wav))
        self._run_bg(lambda: modlib.apply_song(wav, game, log=self.log))

    def on_restore(self):
        game = self.var_game.get().strip()
        if not game:
            messagebox.showerror('错误', '请先选择游戏根目录')
            return
        self.log('==== 还原官方原版 ====')
        self._run_bg(lambda: modlib.restore(game, log=self.log))


if __name__ == '__main__':
    App().mainloop()
