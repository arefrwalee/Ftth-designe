# -*- coding: utf-8 -*-
"""واجهة رسومية لمصمم الدراسات الهوائية (Tkinter، بلا خريطة).
كل زر يشغّل أمر الأداة نفسه في عملية منفصلة ويعرض مخرجاته بالعربية في المربع السفلي، فلا منطق جديد هنا.
اتجاه العربية: Windows يعرضها صحيحة عادةً؛ إن ظهرت معكوسة غيّر «عرض العربية» أعلى النافذة (يُحفظ).
"""
import os, sys, json, threading, queue, subprocess, glob
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__)); PKG = os.path.abspath(os.path.join(HERE, '..'))
FROZEN = bool(getattr(sys, 'frozen', False))
sys.path.insert(0, HERE)
import ftth_ar

SETTINGS = os.path.join(os.path.expanduser('~'), '.ftth_designer_gui.json')
IS_NT = os.name == 'nt'
FONT = ('Segoe UI', 11) if IS_NT else ('DejaVu Sans', 11)


def load_settings():
    try: return json.load(open(SETTINGS, encoding='utf-8'))
    except Exception: return {}


def save_settings(d):
    try: json.dump(d, open(SETTINGS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception: pass


def python_exe():
    p = os.environ.get('FTTH_PY')
    if p: return p
    exe = sys.executable
    if os.path.basename(exe).lower() == 'pythonw.exe':
        cand = os.path.join(os.path.dirname(exe), 'python.exe')
        if os.path.exists(cand): return cand
    return exe


def open_path(p):
    try:
        if IS_NT: os.startfile(p)
        elif sys.platform == 'darwin': subprocess.Popen(['open', p])
        else: subprocess.Popen(['xdg-open', p])
    except Exception as e:
        messagebox.showerror('خطأ', str(e))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings(); self.q = queue.Queue(); self.busy = False; self.reg = []
        self.MODES = {'Windows (word order)': 'words', 'Full shaping (Linux)': 'full', 'No fix': 'none'}
        cur = self.cfg.get('arabic_mode', 'words' if IS_NT else 'full')
        self.fix = tk.StringVar(value=next(k for k, v in self.MODES.items() if v == cur))
        self.title(self.T('مصمم الدراسات الهوائية')); self.geometry('860x720'); self.minsize(720, 600)
        st = ttk.Style(self)
        try: st.theme_use('clam' if not IS_NT else 'vista')
        except Exception: pass
        for s in ('TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TNotebook.Tab'): st.configure(s, font=FONT)
        self.vars = {k: tk.StringVar(value=self.cfg.get(k, '')) for k in
                     ('study', 'poles', 'din', 'dout', 'dstudy', 'qgpkg', 'qtown', 'nname', 'ntown', 'ngpkg', 'nref')}
        self.force = tk.BooleanVar(value=False)
        top = ttk.Frame(self); top.pack(fill='x', padx=10, pady=(8, 0))
        self.lbl(top, 'مصمم الدراسات الهوائية', font=(FONT[0], 15, 'bold')).pack(side='right')
        cb = ttk.Combobox(top, textvariable=self.fix, values=list(self.MODES), state='readonly', width=22, justify='right')
        cb.pack(side='left'); cb.bind('<<ComboboxSelected>>', lambda e: self.retranslate())
        self.lbl(top, 'عرض العربية:').pack(side='left', padx=6)
        nb = ttk.Notebook(self); nb.pack(fill='x', padx=10, pady=8); self.nb = nb
        self.tab_update(nb); self.tab_draft(nb); self.tab_maps(nb); self.tab_new(nb)
        self.status = self.lbl(self, '', anchor='e'); self.status.pack(fill='x', padx=12)
        fr = ttk.Frame(self); fr.pack(fill='both', expand=True, padx=10, pady=(2, 10))
        self.log = tk.Text(fr, height=14, wrap='word', font=('Consolas' if IS_NT else 'DejaVu Sans Mono', 10), state='disabled')
        sb = ttk.Scrollbar(fr, command=self.log.yview); self.log.configure(yscrollcommand=sb.set)
        sb.pack(side='left', fill='y'); self.log.pack(side='right', fill='both', expand=True)
        self.log.tag_configure('rtl', justify='right'); self.log.tag_configure('err', foreground='#b71c1c')
        self.retranslate(); self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        if self.vars["study"].get(): self.study_changed()

    # ---------- نص عربي
    def mode(self): return self.MODES.get(self.fix.get(), 'none')

    def T(self, s):
        m = self.mode()
        if m == 'none': return s
        if m == 'full': return '\n'.join(ftth_ar.visual(ftth_ar.shape(l)) for l in s.split('\n'))
        # words: Tk على ويندوز يصل الحروف لكن اتجاهه يسار->يمين، فنعكس ترتيب الكلمات فقط
        out = []
        for l in s.split('\n'):
            out.append(' '.join(reversed(l.split(' '))) if any('\u0600' <= c <= '\u06ff' for c in l) else l)
        return '\n'.join(out)

    def lbl(self, parent, text, **kw):
        w = ttk.Label(parent, **kw); self.reg.append((lambda t, w=w: w.configure(text=t), text)); return w

    def btn(self, parent, text, cmd):
        w = ttk.Button(parent, command=cmd); self.reg.append((lambda t, w=w: w.configure(text=t), text)); return w

    def retranslate(self):
        for setter, text in self.reg: setter(self.T(text))
        for i, (_, txt) in enumerate(self.tabs): self.nb.tab(i, text=self.T(txt))
        self.title(self.T('مصمم الدراسات الهوائية'))
        self.cfg['arabic_mode'] = self.mode(); save_settings(self.cfg)

    # ---------- صفوف الإدخال (ترتيب يمين->يسار: تسمية | حقل | زر)
    def row(self, f, r, label, var, kind=None, filetypes=None):
        self.lbl(f, label).grid(row=r, column=2, sticky='e', padx=6, pady=4)
        e = ttk.Entry(f, textvariable=var, justify='right'); e.grid(row=r, column=1, sticky='ew', pady=4)
        if kind:
            def pick():
                if kind == 'dir': p = filedialog.askdirectory(initialdir=var.get() or None)
                else: p = filedialog.askopenfilename(initialdir=os.path.dirname(var.get()) if var.get() else None, filetypes=filetypes or [('All', '*.*')])
                if p: var.set(p); self.persist(); self.study_changed() if var is self.vars['study'] else None
            self.btn(f, 'استعراض', pick).grid(row=r, column=0, padx=6)
        f.columnconfigure(1, weight=1)
        return e

    tabs = []

    def add_tab(self, nb, title):
        f = ttk.Frame(nb, padding=10); nb.add(f, text=title)
        if not hasattr(self, '_t'): self._t = []
        self._t.append((f, title)); self.tabs = self._t
        return f

    def tab_update(self, nb):
        f = self.add_tab(nb, 'تحديث دراسة')
        self.row(f, 0, 'مجلد أداة_التحديث للدراسة', self.vars['study'], 'dir')
        self.row(f, 1, 'ملف الأعمدة من المسح (اختياري)', self.vars['poles'], 'file', [('Poles', '*.csv *.gpkg'), ('All', '*.*')])
        c = ttk.Checkbutton(f, variable=self.force); c.grid(row=2, column=1, sticky='e'); self.reg.append((lambda t, w=c: w.configure(text=t), 'تابع رغم الأخطاء (--force)'))
        b = ttk.Frame(f); b.grid(row=3, column=0, columnspan=3, sticky='e', pady=6)
        self.btn(b, 'فتح مجلد النتائج', self.open_results).pack(side='left', padx=4)
        self.btn(b, 'تشغيل التحديث', self.run_update).pack(side='left', padx=4)

    def tab_draft(self, nb):
        f = self.add_tab(nb, 'مسودة تصميم')
        self.row(f, 0, 'gpkg فيه المباني والطرق والمركز', self.vars['din'], 'file', [('GeoPackage', '*.gpkg')])
        self.row(f, 1, 'مجلد المخرجات (اختياري)', self.vars['dout'], 'dir')
        self.row(f, 2, 'مجلد دراسة لأخذ المعايير منه (اختياري)', self.vars['dstudy'], 'dir')
        b = ttk.Frame(f); b.grid(row=3, column=0, columnspan=3, sticky='e', pady=6)
        self.btn(b, 'فتح مجلد المسودة', lambda: self.open_dir(self.draft_out())).pack(side='left', padx=4)
        self.btn(b, 'توليد المسودة', self.run_draft).pack(side='left', padx=4)

    def tab_maps(self, nb):
        f = self.add_tab(nb, 'مشروع QGIS وخرائط')
        self.row(f, 0, 'ملف gpkg', self.vars['qgpkg'], 'file', [('GeoPackage', '*.gpkg')])
        self.row(f, 1, 'اسم البلدة', self.vars['qtown'])
        b = ttk.Frame(f); b.grid(row=2, column=0, columnspan=3, sticky='e', pady=6)
        self.btn(b, 'خرائط PDF', self.run_pdf).pack(side='left', padx=4)
        self.btn(b, 'بناء مشروع QGIS', self.run_qgis).pack(side='left', padx=4)

    def tab_new(self, nb):
        f = self.add_tab(nb, 'دراسة جديدة')
        self.row(f, 0, 'اسم لاتيني قصير (مثال Salqin)', self.vars['nname'])
        self.row(f, 1, 'اسم البلدة بالعربية', self.vars['ntown'])
        self.row(f, 2, 'ملف gpkg الجديد', self.vars['ngpkg'], 'file', [('GeoPackage', '*.gpkg')])
        self.row(f, 3, 'مجلد أداة_التحديث لدراسة مرجعية', self.vars['nref'], 'dir')
        b = ttk.Frame(f); b.grid(row=4, column=0, columnspan=3, sticky='e', pady=6)
        self.btn(b, 'إنشاء الدراسة', self.run_new).pack(side='left', padx=4)

    # ---------- حالة
    def persist(self):
        for k, v in self.vars.items(): self.cfg[k] = v.get()
        save_settings(self.cfg)

    def on_close(self): self.persist(); self.destroy()

    def study_json(self, d=None):
        d = d or self.vars['study'].get().strip()
        try: return json.load(open(os.path.join(d, 'study.json'), encoding='utf-8')), d
        except Exception: return None, d

    def study_changed(self):
        cfg, d = self.study_json()
        if not cfg:
            self.set_status('المجلد المختار لا يحوي study.json' if d else ''); return
        self.set_status('الدراسة: %s (%s)' % (cfg.get('town_ar', ''), cfg.get('study', '')))
        gp = os.path.join(os.path.dirname(d), cfg.get('gpkg', ''))
        if not self.vars['qgpkg'].get(): self.vars['qgpkg'].set(gp)
        if not self.vars['qtown'].get(): self.vars['qtown'].set(cfg.get('town_ar', ''))
        if not self.vars['dstudy'].get(): self.vars['dstudy'].set(d)
        if not self.vars['nref'].get(): self.vars['nref'].set(d)

    def set_status(self, s):
        self._status_logical = s; self.status.configure(text=self.T(s))

    # ---------- تشغيل عمليات
    def write(self, line, tag=None):
        line = line.rstrip('\r\n')
        rtl = any('؀' <= ch <= 'ۿ' for ch in line)
        txt = self.T(line) if rtl else line
        self.log.configure(state='normal'); self.log.insert('end', txt + '\n', tuple(t for t in ((('rtl',) if rtl else ()) + ((tag,) if tag else ()))))
        self.log.see('end'); self.log.configure(state='disabled')

    def run(self, args, done=None, label=''):
        if self.busy: return
        self.persist(); self.busy = True; self.set_status('جارٍ التنفيذ: ' + label)
        self.write('>>> ' + label)
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', FTTH_AR='0')
        cmd = [sys.executable, '--run'] + args if FROZEN else [python_exe(), '-u'] + args
        def work():
            try:
                kw = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=PKG, env=env, stdin=subprocess.DEVNULL)
                if IS_NT: kw['creationflags'] = 0x08000000
                p = subprocess.Popen(cmd, **kw)
                for raw in p.stdout: self.q.put(('line', raw.decode('utf-8', 'replace')))
                p.wait(); self.q.put(('end', p.returncode, done))
            except Exception as e:
                self.q.put(('line', 'ERROR: %s' % e)); self.q.put(('end', -1, done))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'line': self.write(m[1], 'err' if m[1].startswith(('Traceback', 'ERROR')) else None)
                else:
                    self.busy = False; rc, done = m[1], m[2]
                    self.set_status('انتهى بنجاح' if rc == 0 else 'انتهى بخطأ (رمز %s) راجع السجل' % rc)
                    if done and rc == 0: done()
        except queue.Empty: pass
        self.after(100, self.poll)

    def need(self, *keys):
        for k in keys:
            if not self.vars[k].get().strip():
                messagebox.showwarning(self.T('ناقص'), self.T('أكمل الحقول المطلوبة')); return False
        return True

    def run_update(self):
        if not self.need('study'): return
        if not os.path.exists(os.path.join(self.vars['study'].get(), 'study.json')):
            messagebox.showerror(self.T('خطأ'), self.T('المجلد لا يحوي study.json')); return
        a = [os.path.join('core', 'ftth_update.py'), '--study', self.vars['study'].get().strip()]
        if self.vars['poles'].get().strip(): a += ['--poles', self.vars['poles'].get().strip()]
        if self.force.get(): a.append('--force')
        self.run(a, label='تحديث الدراسة', done=self.open_results)

    def open_results(self):
        d = os.path.join(self.vars['study'].get().strip(), 'نتائج_التحديث')
        subs = sorted(glob.glob(os.path.join(d, '*')))
        if subs: open_path(subs[-1])
        elif os.path.isdir(d): open_path(d)
        else: messagebox.showinfo(self.T('لا نتائج'), self.T('لم تُشغَّل الدراسة بعد'))

    def draft_out(self):
        if self.vars['dout'].get().strip(): return self.vars['dout'].get().strip()
        g = self.vars['din'].get().strip()
        return (os.path.splitext(g)[0] + '_draft') if g else ''

    def open_dir(self, d):
        if d and os.path.isdir(d): open_path(d)
        else: messagebox.showinfo(self.T('لا مجلد'), self.T('لم تُولَّد مسودة بعد'))

    def run_draft(self):
        if not self.need('din'): return
        a = [os.path.join('core', 'ftth_design.py'), '--input', self.vars['din'].get().strip(), '--out', self.draft_out()]
        if self.vars['dstudy'].get().strip(): a += ['--study', self.vars['dstudy'].get().strip()]
        self.run(a, label='توليد مسودة التصميم', done=lambda: self.write('راجع FTTH_draft.gpkg في QGIS وعدّله قبل التحديث'))

    def run_qgis(self):
        if not self.need('qgpkg', 'qtown'): return
        g = self.vars['qgpkg'].get().strip()
        self.run([os.path.join('core', 'ftth_qgis.py'), '--gpkg', g, '--out', os.path.dirname(g), '--town', self.vars['qtown'].get().strip()], label='بناء مشروع QGIS',
                 done=lambda: self.open_dir(os.path.dirname(g)))

    def run_pdf(self):
        if not self.need('qgpkg', 'qtown'): return
        g = self.vars['qgpkg'].get().strip()
        self.run([os.path.join('core', 'ftth_maps.py'), '--gpkg', g, '--town', self.vars['qtown'].get().strip()], label='خرائط PDF',
                 done=lambda: self.open_dir(os.path.dirname(g)))

    def run_new(self):
        if not self.need('nname', 'ntown', 'ngpkg', 'nref'): return
        v = self.vars
        self.run([os.path.join('core', 'new_study.py'), '--name', v['nname'].get().strip(), '--town', v['ntown'].get().strip(),
                  '--gpkg', v['ngpkg'].get().strip(), '--from', v['nref'].get().strip()], label='إنشاء دراسة جديدة')


def main():
    App().mainloop()


if __name__ == '__main__':
    main()
