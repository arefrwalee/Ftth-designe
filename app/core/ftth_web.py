# -*- coding: utf-8 -*-
"""واجهة «مصمم الدراسات الهوائية»: خادم محلي صغير + نافذة تطبيق (Edge/Chrome بوضع --app). بلا مكتبات خارجية.
الواجهة (web/index.html) تستدعي واجهة JSON هنا؛ كل عملية ثقيلة تُشغَّل كعملية منفصلة بنفس أدوات سطر الأوامر."""
import os, sys, json, threading, subprocess, time, glob, shutil, tempfile, webbrowser, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__)); PKG = os.path.abspath(os.path.join(HERE, '..'))
WEB = os.path.join(HERE, 'web'); sys.path.insert(0, HERE)
IS_NT = os.name == 'nt'
SETTINGS = os.path.join(os.path.expanduser('~'), '.ftth_designer.json')
JOBS = {}; LAST_PING = [0.0]; SEEN_PING = [False]


def load_settings():
    try: return json.load(open(SETTINGS, encoding='utf-8'))
    except Exception: return {}

def save_settings(d):
    try: json.dump(d, open(SETTINGS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception: pass

def workspace():
    w = load_settings().get('workspace') or os.path.join(os.path.expanduser('~'), 'Documents', 'مصمم الدراسات الهوائية')
    os.makedirs(w, exist_ok=True); return w

def python_exe():
    exe = sys.executable
    if os.path.basename(exe).lower() == 'pythonw.exe':
        c = os.path.join(os.path.dirname(exe), 'python.exe')
        if os.path.exists(c): return c
    return exe

def open_path(p):
    if IS_NT: os.startfile(p)
    elif sys.platform == 'darwin': subprocess.Popen(['open', p])
    else: subprocess.Popen(['xdg-open', p])

# ---------------------------------------------------------------- native pickers (tkinter in a child process)
PICK = r'''
import sys, tkinter as tk
from tkinter import filedialog
r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)
k = sys.argv[1]
p = filedialog.askdirectory(title=sys.argv[2]) if k == 'folder' else filedialog.askopenfilename(title=sys.argv[2], filetypes=[(sys.argv[3], sys.argv[4]), ('كل الملفات', '*.*')])
sys.stdout.buffer.write((p or '').encode('utf-8'))
'''
def pick(kind, title, label='', pat='*.*'):
    try:
        out = subprocess.run([python_exe(), '-c', PICK, kind, title, label, pat], capture_output=True, timeout=600)
        return out.stdout.decode('utf-8', 'replace').strip()
    except Exception: return ''

# ---------------------------------------------------------------- studies
def studies():
    res = []
    for sj in sorted(glob.glob(os.path.join(workspace(), '*_10y', 'أداة_التحديث', 'study.json'))):
        try: c = json.load(open(sj, encoding='utf-8'))
        except Exception: continue
        tool = os.path.dirname(sj)
        res.append(dict(name=c['study'], town=c.get('town_ar', c['study']), tool=tool, dir=os.path.dirname(tool), generic=bool(c.get('generic')),
                        results=os.path.join(tool, 'نتائج_التحديث')))
    return res

def find_study(name):
    return next((s for s in studies() if s['name'] == name), None)

IN_CELLS = {'months': 'B3', 'fuel': 'B4', 'excavation': 'B5', 'manholes': 'B6', 'hanging': 'B7'}

def study_data(name):
    import openpyxl
    from ftth_update import rows_by_label
    s = find_study(name)
    if not s: return {'error': 'الدراسة غير موجودة'}
    cfg = json.load(open(os.path.join(s['tool'], 'study.json'), encoding='utf-8'))
    if not cfg.get('generic'): return dict(generic=False, town=s['town'])
    wb = openpyxl.load_workbook(os.path.join(s['tool'], cfg['templates'][0]))
    ws1 = wb['الكميات_الحالية']; ws2 = wb['الكميات_بعد_10_سنوات']
    r2 = {t: r for r, t in rows_by_label(ws2).items()}
    items = []
    for r, t in rows_by_label(ws1).items():
        q1 = ws1.cell(r, 5).value; q2 = ws2.cell(r2[t], 5).value if t in r2 else None
        items.append(dict(label=t, unit=str(ws1.cell(r, 4).value).split('/')[0].strip(), q1=q1 if isinstance(q1, (int, float)) else None, q10=q2 if isinstance(q2, (int, float)) else None, formula=isinstance(q1, str)))
    inp = {}
    for k, cell in IN_CELLS.items():
        v = wb['مدخلات'][cell].value; inp[k] = v if isinstance(v, (int, float)) else None
    pf = os.path.join(s['tool'], 'الأسعار.json'); prices = {'real': {}, 'company': {}}
    if os.path.exists(pf):
        try: prices = json.load(open(pf, encoding='utf-8'))
        except Exception: pass
    return dict(generic=True, town=s['town'], items=items, inputs=inp, prices={k: prices.get(k, {}) for k in ('real', 'company')})

def save_study(name, inputs, prices):
    import openpyxl
    s = find_study(name); cfg = json.load(open(os.path.join(s['tool'], 'study.json'), encoding='utf-8'))
    clean = {k: {l: (float(v) if v not in (None, '') else None) for l, v in (prices.get(k) or {}).items()} for k in ('real', 'company')}
    json.dump(dict({'_note': 'أسعار الوحدة بالدولار. null = غير مسعّر'}, **clean), open(os.path.join(s['tool'], 'الأسعار.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for tpl in cfg['templates']:
        p = os.path.join(s['tool'], tpl); wb = openpyxl.load_workbook(p); ws = wb['مدخلات']
        for k, cell in IN_CELLS.items():
            v = inputs.get(k)
            if v in (None, ''):
                if k == 'fuel': ws[cell].value = '=B3'
                continue
            ws[cell].value = float(v) if k != 'months' and k != 'fuel' else float(v)
        wb.save(p)
    return True

# ---------------------------------------------------------------- jobs
def start_job(args):
    jid = uuid.uuid4().hex[:8]; job = dict(lines=[], done=False, code=None, out=None); JOBS[jid] = job
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', FTTH_AR='0')
    def run():
        try:
            p = subprocess.Popen([python_exe(), '-u'] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL,
                                 creationflags=0x08000000 if IS_NT else 0)
            for raw in p.stdout: job['lines'].append(raw.decode('utf-8', 'replace').rstrip('\r\n'))
            job['code'] = p.wait()
        except Exception as e:
            job['lines'].append('خطأ: %s' % e); job['code'] = 1
        job['done'] = True
    threading.Thread(target=run, daemon=True).start()
    return jid

def build_args(d):
    j = d['job']; ws = workspace()
    if j == 'full':
        a = [os.path.join(HERE, 'ftth_full.py'), '--input', d['input'], '--name', d['name'], '--town', d['town'], '--out', ws]
        if d.get('poles'): a += ['--poles', d['poles']]
        return a
    if j == 'update':
        s = find_study(d['name']); a = [os.path.join(HERE, 'ftth_update.py'), '--study', s['tool']]
        if d.get('poles'): a += ['--poles', d['poles']]
        if d.get('force'): a += ['--force']
        return a
    raise ValueError(j)

# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200, ctype='application/json; charset=utf-8'):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == '/api/ping': LAST_PING[0] = time.time(); SEEN_PING[0] = True; return self._send({'ok': 1})
            if u.path == '/api/state':
                st = load_settings(); return self._send(dict(workspace=workspace(), studies=studies(), version=1))
            if u.path == '/api/study': return self._send(study_data(q['name']))
            if u.path == '/api/job':
                j = JOBS.get(q['id']); n = int(q.get('since', 0))
                return self._send(dict(lines=j['lines'][n:], next=len(j['lines']), done=j['done'], code=j['code']))
            f = 'index.html' if u.path in ('/', '') else u.path.lstrip('/')
            p = os.path.abspath(os.path.join(WEB, f))
            if not p.startswith(WEB) or not os.path.isfile(p): return self._send({'error': 'not found'}, 404)
            ct = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png'}.get(os.path.splitext(p)[1], 'application/octet-stream')
            return self._send(open(p, 'rb').read(), 200, ct)
        except Exception as e: return self._send({'error': str(e)}, 500)
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get('Content-Length') or 0)
        d = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
        try:
            if u.path == '/api/pick': return self._send(dict(path=pick(d['kind'], d.get('title', ''), d.get('label', ''), d.get('pattern', '*.*'))))
            if u.path == '/api/run': return self._send(dict(id=start_job(build_args(d))))
            if u.path == '/api/study/save': return self._send(dict(ok=save_study(d['name'], d.get('inputs', {}), d.get('prices', {}))))
            if u.path == '/api/open':
                p = d['path']
                if d.get('what') == 'results':
                    s = find_study(d['name']); r = sorted(glob.glob(os.path.join(s['results'], '*'))); p = r[-1] if r else s['dir']
                elif d.get('what') == 'study': p = find_study(d['name'])['dir']
                elif d.get('what') == 'workspace': p = workspace()
                open_path(p); return self._send({'ok': 1})
            if u.path == '/api/settings':
                st = load_settings(); st.update(d); save_settings(st); return self._send({'ok': 1})
            return self._send({'error': 'unknown'}, 404)
        except Exception as e: return self._send({'error': str(e)}, 500)

def find_browser():
    c = []
    if IS_NT:
        for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
            if base:
                c += [os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')]
    else:
        c = [shutil.which(x) for x in ('chromium', 'chromium-browser', 'google-chrome', 'microsoft-edge')]
    return next((x for x in c if x and os.path.exists(x)), None)

def main():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % port; br = find_browser(); LAST_PING[0] = time.time()
    if '--no-window' in sys.argv: print(url, flush=True)
    elif br:
        prof = os.path.join(tempfile.gettempdir(), 'ftth_designer_profile')
        subprocess.Popen([br, '--app=' + url, '--user-data-dir=' + prof, '--window-size=1240,820', '--no-first-run', '--lang=ar'])
    else: webbrowser.open(url)
    t0 = time.time()
    while True:
        time.sleep(1)
        if SEEN_PING[0] and time.time() - LAST_PING[0] > 20: break
        if not SEEN_PING[0] and time.time() - t0 > 90: break

if __name__ == '__main__': main()
