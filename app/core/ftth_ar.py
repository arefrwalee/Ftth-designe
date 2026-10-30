# -*- coding: utf-8 -*-
"""Arabic display for cmd.exe: the Windows console neither joins Arabic letters nor reorders right-to-left text.
This module converts a logical Arabic line to the *visual* line (joined presentation forms, reversed order) so it
reads correctly in a left-to-right console. Pure Python, no dependencies. Files (run_summary.txt etc.) keep the logical text."""
import os, re, sys, shutil, unicodedata

# base: (isolated, final, initial, medial); None = form does not exist
_D = lambda c: (c, c + 1, c + 2, c + 3)     # dual-joining letters: 4 consecutive presentation forms
_R = lambda c: (c, c + 1, None, None)       # right-joining letters: isolated + final
FORMS = {
 '\u0621': (0xFE80, None, None, None), '\u0622': _R(0xFE81), '\u0623': _R(0xFE83), '\u0624': _R(0xFE85), '\u0625': _R(0xFE87),
 '\u0626': _D(0xFE89), '\u0627': _R(0xFE8D), '\u0628': _D(0xFE8F), '\u0629': _R(0xFE93), '\u062A': _D(0xFE95), '\u062B': _D(0xFE99),
 '\u062C': _D(0xFE9D), '\u062D': _D(0xFEA1), '\u062E': _D(0xFEA5), '\u062F': _R(0xFEA9), '\u0630': _R(0xFEAB), '\u0631': _R(0xFEAD),
 '\u0632': _R(0xFEAF), '\u0633': _D(0xFEB1), '\u0634': _D(0xFEB5), '\u0635': _D(0xFEB9), '\u0636': _D(0xFEBD), '\u0637': _D(0xFEC1),
 '\u0638': _D(0xFEC5), '\u0639': _D(0xFEC9), '\u063A': _D(0xFECD), '\u0641': _D(0xFED1), '\u0642': _D(0xFED5), '\u0643': _D(0xFED9),
 '\u0644': _D(0xFEDD), '\u0645': _D(0xFEE1), '\u0646': _D(0xFEE5), '\u0647': _D(0xFEE9), '\u0648': _R(0xFEED), '\u0649': _R(0xFEEF),
 '\u064A': _D(0xFEF1), '\u0640': ('\u0640', '\u0640', '\u0640', '\u0640'),
}
LAM_ALEF = {'\u0622': (0xFEF5, 0xFEF6), '\u0623': (0xFEF7, 0xFEF8), '\u0625': (0xFEF9, 0xFEFA), '\u0627': (0xFEFB, 0xFEFC)}
MARKS = re.compile('[\u064B-\u065F\u0670\u06D6-\u06ED]')   # tashkeel: dropped (a console cell cannot hold combining marks)
ARABIC = re.compile('[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
MIRROR = {'(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{', '<': '>', '>': '<', '«': '»', '»': '«'}

def _can_join_next(ch):   # does this letter connect to the letter after it (on its left)?
    f = FORMS.get(ch); return bool(f and f[2] is not None)
def _is_letter(ch): return ch in FORMS

def shape(text):
    """logical Arabic -> presentation forms (still in logical order)"""
    text = MARKS.sub('', text); out = []; n = len(text); i = 0
    while i < n:
        ch = text[i]
        if not _is_letter(ch): out.append(ch); i += 1; continue
        prev_joins = i > 0 and _can_join_next(text[i - 1])
        if ch == '\u0644' and i + 1 < n and text[i + 1] in LAM_ALEF:      # lam-alef ligature
            iso, fin = LAM_ALEF[text[i + 1]]; out.append(chr(fin if prev_joins else iso)); i += 2; continue
        f = FORMS[ch]; next_joins = _can_join_next(ch) and i + 1 < n and _is_letter(text[i + 1])
        if next_joins and prev_joins: form = f[3]
        elif next_joins: form = f[2]
        elif prev_joins: form = f[1]
        else: form = f[0]
        if form is None: form = f[1] if (prev_joins and f[1]) else f[0]
        out.append(form if isinstance(form, str) else chr(form)); i += 1
    return ''.join(out)

def _cls(ch):
    bd = unicodedata.bidirectional(ch)
    if bd in ('AL', 'R'): return 'R'
    if bd in ('EN', 'AN'): return 'EN'
    if bd == 'L': return 'L'
    return 'N'          # includes the Arabic comma (CS) and punctuation

def visual(line):
    """logical -> visual order for a left-to-right console (simplified Unicode bidi)"""
    cl = [_cls(c) for c in line]; n = len(line)
    # numbers: digits joined by . , : / between digits, and % $ + - touching a digit
    for i, c in enumerate(line):
        if cl[i] == 'N' and c in '.,:/' and 0 < i < n - 1 and cl[i - 1] == 'EN' and cl[i + 1] == 'EN': cl[i] = 'EN'
    for i, c in enumerate(line):
        if cl[i] == 'N' and c in '%$+-' and ((i > 0 and cl[i - 1] == 'EN') or (i < n - 1 and cl[i + 1] == 'EN')): cl[i] = 'EN'
    first = next((x for x in cl if x in ('R', 'L')), None)
    base = 1 if first == 'R' else 0
    lvl = [None] * n
    for i, k in enumerate(cl):
        lvl[i] = 1 if k == 'R' else (base + 1 if base == 1 else 0) if k in ('L', 'EN') else None
        if k in ('L', 'EN') and base == 1: lvl[i] = 2
        if k in ('L', 'EN') and base == 0: lvl[i] = 0
    # keep a bracket pair inside a Latin/digit run when both ends sit in it ("(Class B+)"), and a "+" glued after Latin ("C+")
    for i, c in enumerate(line):
        if lvl[i] is None and c in '([{' and i < n - 1 and cl[i + 1] in ('L', 'EN'):
            cl_ = {'(': ')', '[': ']', '{': '}'}[c]; r = next((k for k in range(i + 1, n) if cl[k] == 'R'), n)
            k = line.find(cl_, i + 1)
            if 0 < k < r and lvl[k] is None and cl[k - 1] in ('L', 'EN', 'N'):
                lvl[i] = lvl[i + 1]; lvl[k] = lvl[i + 1]
    for i, c in enumerate(line):
        if lvl[i] is None and c == '+' and i > 0 and lvl[i - 1] in (0, 2) and cl[i - 1] in ('L', 'EN'): lvl[i] = lvl[i - 1]
    for i in range(n):                         # neutrals take the level of equal neighbours, else the base level
        if lvl[i] is None:
            a = next((lvl[j] for j in range(i - 1, -1, -1) if lvl[j] is not None), base)
            b = next((lvl[j] for j in range(i + 1, n) if lvl[j] is not None), base)
            la = base if a is None else (1 if a == 1 else (2 if a == 2 else 0)); lb = base if b is None else (1 if b == 1 else (2 if b == 2 else 0))
            lvl[i] = la if la == lb else base
    # reorder (rule L2)
    chars = list(line); levels = lvl[:]
    for c in range(max(levels or [0]), 0, -1):
        i = 0
        while i < n:
            if levels[i] >= c:
                j = i
                while j < n and levels[j] >= c: j += 1
                chars[i:j] = chars[i:j][::-1]; levels[i:j] = levels[i:j][::-1]; i = j
            else: i += 1
    # mirror brackets that ended up in right-to-left runs
    out = []
    for ch, l in zip(chars, levels): out.append(MIRROR.get(ch, ch) if l % 2 == 1 and ch in MIRROR else ch)
    return ''.join(out)

def fix_line(line, width=0):
    """one logical line -> console line(s). Wraps long lines on spaces so each wrapped piece is shaped on its own."""
    if not ARABIC.search(line): return line
    if width and len(line) > width:
        words = line.split(' '); parts = []; cur = ''
        for w in words:
            if cur and len(cur) + 1 + len(w) > width: parts.append(cur); cur = w
            else: cur = (cur + ' ' + w) if cur else w
        if cur: parts.append(cur)
    else: parts = [line]
    res = []
    for p in parts:
        v = visual(shape(p))
        if width and ARABIC.search(p) and base_rtl(p): v = v.rjust(width)
        res.append(v)
    return '\n'.join(res)

def base_rtl(line):
    first = next((_cls(c) for c in line if _cls(c) in ('R', 'L')), None); return first == 'R'

class Out:
    """stdout wrapper: console gets visual Arabic, the optional tee file gets the logical text"""
    def __init__(self, stream, shaping=True, tee=None):
        self.s = stream; self.shaping = shaping; self.tee = tee; self.buf = ''
    def set_tee(self, f): self.tee = f
    def write(self, text):
        if self.tee: self.tee.write(text)
        if not self.shaping: return self.s.write(text)
        self.buf += text; w = shutil.get_terminal_size((100, 25)).columns - 1; res = ''
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1); res += fix_line(line, w) + '\n'
        if res: self.s.write(res)
    def flush(self):
        if self.buf and self.shaping: self.s.write(fix_line(self.buf)); self.buf = ''
        self.s.flush()
    def __getattr__(self, k): return getattr(self.s, k)

def want_shaping(mode):
    """mode: True / False / 'auto' (auto = only in a real Windows console; FTTH_AR=1 or 0 overrides)"""
    env = os.environ.get('FTTH_AR')
    if env in ('0', '1'): return env == '1'
    if mode is True or mode is False: return mode
    try: return os.name == 'nt' and sys.stdout.isatty()
    except Exception: return False

def install(mode='auto'):
    out = Out(sys.stdout, want_shaping(mode)); sys.stdout = out; return out
