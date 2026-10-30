# -*- coding: utf-8 -*-
"""Generic BOQ: quantities only (no prices), current + 10-year growth model. Prices are applied later from a local prices file."""
import sys, os, json, re
from math import ceil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GROWTH_DEFAULT = {"rate": 0.05, "years": 10, "subs_per_secondary": 6, "secondaries_per_primary": 6}

def _c(x): return int(ceil(x - 1e-9))

def growth_model(m, STD, g=None):
    """m = metrics dict (ftth_update.metrics) of the CURRENT design (net counts). Returns year-10 quantities.
    Rules (calibrated on Orem): new subs = round(subs*(1+r)^y) - subs; new secondaries = ceil(new/subs_per_sec);
    new primaries = ceil(new_sec/sec_per_prim); closures follow today's closures-per-primary ratio;
    branch cables scale with new primaries / today's primaries; main cables unchanged."""
    g = dict(GROWTH_DEFAULT, **(g or {}))
    sp = STD['spare']['splitters_closures']
    subs0 = int(m['subs']); subs10 = int(round(subs0 * (1 + g['rate']) ** g['years']))
    new_sec = _c((subs10 - subs0) / g['subs_per_secondary'])
    new_prim = _c(new_sec / g['secondaries_per_primary'])
    KP, K, NC = m['KP'], m['K'], m['NC']
    new_clo = _c(new_prim * NC / KP) if KP else 0
    k = (new_prim / KP) if KP else 0
    out = dict(subs0=subs0, subs10=subs10, new_sec=new_sec, new_prim=new_prim, new_clo=new_clo,
               KP10=KP + new_prim, K10=K + new_sec, NC10=NC + new_clo)
    out['branch_add'] = {key: v * k for key, v in m.items() if re.match(r'B\d+$', key)}
    out['PON10'] = out['KP10'] + STD['pon']['extra_ports']
    out['ODF10'] = max(m.get('ODF', 0), _c(out['KP10'] / STD['odf']['fibres_per_panel']))
    return out

def quantities(m, STD, g=None):
    """returns (now, y10): dicts keyed by component key -> quantity (spare folded in)"""
    sp = STD['spare']['splitters_closures']; G = growth_model(m, STD, g)
    hb = STD['hanging_by_cable_length']
    hang = lambda tot: _c(tot / hb['span_m'] / hb['round_to']) * hb['round_to']
    def build(KP, K, NC, PON, ODF, mains, branches):
        q = {}
        for key, v in mains.items(): q['M' + key] = _c(v)
        for key, v in branches.items(): q['B' + key] = _c(v)
        q['P'] = _c(KP * sp); q['S'] = _c(K * sp); q['C'] = _c(NC * sp)
        q['gpon'] = _c(PON / STD['pon']['ports_per_card']); q['PON'] = PON
        q['odf'] = ODF; q['patch'] = q['P']; q['cross'] = q['P']
        q['hang'] = hang(sum(v for k_, v in q.items() if re.match(r'[MB]\d+$', k_)))
        q['net'] = dict(KP=KP, K=K, NC=NC)
        return q
    mains = {k[1:]: v for k, v in m.items() if re.match(r'M\d+$', k)}
    br0 = {k[1:]: v for k, v in m.items() if re.match(r'B\d+$', k)}
    br10 = {k[1:]: m[k] + G['branch_add'][k] for k in G['branch_add']}
    now = build(m['KP'], m['K'], m['NC'], m['PON'], m['ODF'], mains, br0)
    y10 = build(G['KP10'], G['K10'], G['NC10'], G['PON10'], G['ODF10'], mains, br10)
    return now, y10, G


# ---------------------------------------------------------------- generic workbook (components only, prices blank)
import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
THIN = Side(style='thin', color='BFC5CF'); BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HFILL = PatternFill('solid', fgColor='14284B'); SFILL = PatternFill('solid', fgColor='E4E9F2'); YFILL = PatternFill('solid', fgColor='FFF2B3')
F_N = Font(name='Arial', size=10); F_B = Font(name='Arial', size=10, bold=True); F_H = Font(name='Arial', size=10, bold=True, color='FFFFFF')
WRAP = Alignment(wrap_text=True, vertical='center', horizontal='right')
INPUTS = 'مدخلات'
# input cells (sheet مدخلات, column B)
IN_ROWS = [('أشهر العمل (مصاريف تأسيسية وأجور)', 3, 'شهر', 'يختلف من دراسة لأخرى. يُدخل بعد تحديد خطة التنفيذ'),
           ('أشهر المحروقات', 4, 'شهر', 'عادة نفس أشهر العمل'),
           ('الحفر (م)', 5, 'م', 'اتركه صفراً إن كانت الشبكة هوائية بالكامل'),
           ('غرف التفتيش', 6, 'عدد', 'اتركه صفراً إن لم يوجد حفر'),
           ('مواد التعليق والتثبيت', 7, 'عدد', 'مقترح من طول الكبلات ÷ 20 م (يقرَّب لأقرب 100). عدّله إن لزم')]

def _label(ar, en): return ar + '\n' + en

def item_list(now, y10, STD):
    """[(section, ar, en, unit_ar, unit_en, desc, key_or_value)] ; key_or_value: ('q',key) | ('const',n) | ('in',row) | ('same',label_prefix)"""
    L = []
    def cab(prefix_ar, prefix_en, tag):
        sizes = sorted({int(k[1:]) for q in (now, y10) for k in q if re.match(r'%s\d+$' % tag, k)}, reverse=True)
        for n in sizes:
            L.append(('أ', '%s %d ألياف' % (prefix_ar, n), '%s %d-core' % (prefix_en, n), 'م', 'm',
                      ('ألياف ضوئية هوائية من المركز إلى السبلترات الرئيسية (الطول المقاس ×%g)' % STD['cable_order_factor']) if tag == 'M' else ('من السبلتر الرئيسي إلى السبلترات الفرعية (×%g)' % STD['cable_order_factor']),
                      ('q', tag + str(n))))
    cab('كابل رئيسي', 'Main cable', 'M'); cab('كابل فرعي', 'Branch cable', 'B')
    pc = round((STD['spare']['splitters_closures'] - 1) * 100)
    L += [('ب', 'سبلتر 1:8 رئيسي', 'Primary splitter 1:8', 'عدد', 'pcs', 'مع احتياط %d%%' % pc, ('q', 'P')),
          ('ب', 'سبلتر 1:8 فرعي', 'Secondary splitter 1:8', 'عدد', 'pcs', 'مع احتياط %d%%' % pc, ('q', 'S')),
          ('ب', 'كلوجر وصل هوائي', 'Aerial splice closure', 'عدد', 'pcs', 'عند التفرعات والدمج، مع احتياط %d%%' % pc, ('q', 'C')),
          ('ج', 'OLT (هيكل مع لوحات التحكم والطاقة)', 'OLT chassis', 'عدد', 'pcs', 'يُحدَّد الطراز مع المورّد', ('const', 1)),
          ('ج', 'بطاقة GPON بـ 16 منفذ', 'GPON service board, 16-port', 'عدد', 'pcs', 'منافذ PON = السبلترات الرئيسية + %d احتياط' % STD['pon']['extra_ports'], ('q', 'gpon')),
          ('ج', 'وحدة SFP لمنفذ GPON (Class C+)', 'GPON OLT SFP module, Class C+', 'عدد', 'pcs', 'تُؤكَّد مع المورّد حسب نوع البطاقة', ('same', 'بطاقة GPON')),
          ('ج', 'Switch تجميع / وصلة صاعدة', 'Aggregation / uplink switch', 'عدد', 'pcs', '', ('const', 1)),
          ('د', 'خزانة شبكة 42U', '42U network cabinet', 'عدد', 'pcs', 'لإيواء OLT والسويتش وODF', ('const', 1)),
          ('د', 'موزع ألياف رئيسي ODF سعة 48 كور', 'Main ODF, 48-core', 'عدد', 'pcs', 'تنتهي عليه ألياف الكبل الرئيسي المستعملة', ('q', 'odf')),
          ('د', 'Patch cord SC/APC', 'SC/APC patch cord', 'عدد', 'pcs', 'واحد لكل منفذ PON', ('q', 'patch')),
          ('د', 'بناء و تركيب تجهيزات غرفة المقسم (OLT، خزانة، ODF، طاقة)', 'CO equipment room works', 'مقطوعية', 'lot', '', ('const', 1)),
          ('د', 'معدات الطاقة (بطارية ليثيوم + إنفرتر + ألواح شمسية + إكسسوارات)', 'Power equipment', 'مقطوعية', 'lot', 'تُحدَّد السعة بعد معرفة حمل المحطة وساعات الاحتياط', ('const', 1)),
          ('هـ', 'متفرقات تثبيت (طوق، جناكل، براغي، حزامات...)', 'Fixing miscellany', 'مقطوعية', 'lot', '', ('const', 1)),
          ('هـ', 'صليب تخزين كابلات على الأعمدة', 'Cable slack storage bracket on poles', 'عدد', 'pcs', '', ('q', 'cross')),
          ('هـ', 'مواد تعليق و تثبيت على الأعمدة', 'Pole hanging & fixing materials', 'عدد', 'pcs', 'اقتراح من طول الكبلات، عدّله من صفحة المدخلات', ('in', 7)),
          ('و', 'عمليات حفر', 'Excavation', 'م', 'm', '', ('in', 5)),
          ('و', 'غرف تفتيش مسبقة الصنع', 'Precast manholes', 'عدد', 'pcs', '', ('in', 6)),
          ('و', 'مصاريف تأسيسية وأجور عمال ومصاريف', 'Setup expenses & labour', 'عدد', 'month', 'لحام ومد كبلات وأجور رافعة وتركيب أعمدة جديدة عند الحاجة ونثريات', ('in', 3)),
          ('و', 'مصاريف محروقات', 'Fuel', 'عدد', 'month', '', ('in', 4)),
          ('و', 'اختبار OTDR للكبلات وملفات QGIS النهائية', 'OTDR testing & final QGIS project', 'مقطوعية', 'lot', '', ('const', 1))]
    return L

SECTIONS = {'أ': 'أ  الكوابل / Cables', 'ب': 'ب  المقسّمات والصناديق / Splitters & enclosures', 'ج': 'ج  المقسم المركزي والمعدات الفعالة / Central office & active equipment',
            'د': 'د  بنية غرفة المقسم / Central office infrastructure', 'هـ': 'هـ  ملحقات الأعمدة والكوابل / Pole & cable accessories', 'و': 'و  أجور التركيب / Installation labour'}

def _hdr(ws, r, vals, fill=HFILL, font=F_H):
    for c, v in enumerate(vals, 1):
        x = ws.cell(r, c, v); x.fill = fill; x.font = font; x.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center'); x.border = BORDER

def _table(wb, name, title, items, q, STD, sub_note):
    ws = wb.create_sheet(name); ws.sheet_view.rightToLeft = True
    ws['A1'] = title; ws['A1'].font = Font(name='Arial', size=13, bold=True); ws['A2'] = sub_note; ws['A2'].font = Font(name='Arial', size=9, italic=True, color='595959')
    _hdr(ws, 4, ['#', 'البند\nItem', 'الوصف\nDescription', 'الوحدة\nUnit', 'الكمية\nQty', 'سعر الوحدة\nUnit price', 'الإجمالي\nTotal'])
    for col, w in zip('ABCDEFG', (5, 46, 44, 12, 11, 13, 14)): ws.column_dimensions[col].width = w
    r = 5; last = None; n = 0; first = 5
    for sec, ar, en, uar, uen, desc, src in items:
        if sec != last:
            ws.cell(r, 1, SECTIONS[sec]).font = F_B
            for c in range(1, 8): ws.cell(r, c).fill = SFILL
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7); r += 1; last = sec
        n += 1
        ws.cell(r, 1, n); ws.cell(r, 2, _label(ar, en)); ws.cell(r, 3, desc); ws.cell(r, 4, '%s / %s' % (uar, uen))
        kind, v = src
        if kind == 'q': qv = q[v]
        elif kind == 'const': qv = v
        elif kind == 'in': qv = "=%s!B%d" % (INPUTS, v) if v != 7 else None
        elif kind == 'same': qv = None
        ws.cell(r, 5, qv)
        ws.cell(r, 7, '=IF(F%d="","",E%d*F%d)' % (r, r, r))
        for c in range(1, 8):
            x = ws.cell(r, c); x.border = BORDER; x.font = F_N; x.alignment = WRAP if c in (2, 3) else Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.cell(r, 6).fill = YFILL; ws.cell(r, 6).number_format = '#,##0.00'; ws.cell(r, 7).number_format = '#,##0.00'
        ws.row_dimensions[r].height = 30
        r += 1
    # derived cells
    rows = {str(ws.cell(i, 2).value).split('\n')[0]: i for i in range(5, r) if ws.cell(i, 2).value}
    for i in range(5, r):
        t = str(ws.cell(i, 2).value or '').split('\n')[0]
        if t.startswith('وحدة SFP'): ws.cell(i, 5).value = '=E%d' % next(j for k, j in rows.items() if k.startswith('بطاقة GPON'))
    ws.cell(r, 1, 'الإجمالي (قبل الهامش) / Total').font = F_B; ws.cell(r, 7, '=SUM(G5:G%d)' % (r - 1)).font = F_B
    ws.cell(r + 1, 1, 'هامش الأمان / Contingency').font = F_B; ws.cell(r + 1, 7, "='بيانات العرض'!$C$25").number_format = '0%'
    ws.cell(r + 2, 1, 'الإجمالي مع الهامش / Total + contingency').font = F_B; ws.cell(r + 2, 7, '=G%d*(1+G%d)' % (r, r + 1)).number_format = '#,##0.00'
    ws.cell(r, 7).number_format = '#,##0.00'
    ws.freeze_panes = 'A5'
    return ws, rows

def create_workbook(path, town, kind, now, y10, G, STD, m, hang_now, hang_10):
    """kind: 'real' | 'company'. Quantities only; unit-price cells are empty and yellow."""
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    items = item_list(now, y10, STD)
    tag = 'العرض الحقيقي (داخلي)' if kind == 'real' else 'عرض الشركة'
    # بيانات العرض
    bd = wb.create_sheet('بيانات العرض'); bd.sheet_view.rightToLeft = True
    bd['A1'] = 'بيانات العرض  |  Offer Details'; bd['A1'].font = Font(name='Arial', size=13, bold=True)
    bd['A2'] = 'شبكة FTTH الهوائية — بلدة %s — %s' % (town, tag)
    rows = [(5, 'الطرف الأول  |  First party', STD['offer'].get('first_party', ''), ''), (6, 'الطرف الثاني  |  Second party', STD['offer'].get('second_party', ''), ''),
            (7, 'اسم المشروع  |  Project', 'تمديد شبكة ألياف ضوئية FTTH هوائية — بلدة %s' % town, ''),
            (10, 'رقم المرجع  |  Reference', None, ''), (11, 'تاريخ العرض  |  Date', datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0), 'تاريخ'),
            (12, 'مدة صلاحية العرض  |  Validity', 30, 'يوم'), (13, 'آخر يوم للصلاحية  |  Valid until', '=C11+C12', 'تاريخ'),
            (14, 'مدة التنفيذ  |  Duration', "=%s!B3" % INPUTS, 'شهر'), (15, 'العملة  |  Currency', 'USD', ''),
            (18, 'المباني المغطاة  |  Buildings covered', m['subs'], 'مبنى'), (19, 'المشتركون المستهدفون  |  Target subscribers', '=C18', 'مشترك'),
            (20, 'السبلترات الفرعية 1:8 (مع احتياط)  |  Secondary splitter', "='الملخص_المالي'!B6", 'عدد'), (21, 'السعة النظرية للمقسمات الثانوية  |  Capacity', '=C20*8', 'منفذ'),
            (22, 'متوسط الفقد المستهدف  |  Avg. loss target', STD['loss']['target_text'], 'dB'), (25, 'احتياطي الطوارئ  |  Contingency', STD['contingency'], '')]
    for r, b, c, d in rows:
        bd.cell(r, 2, b).font = F_B; x = bd.cell(r, 3, c); bd.cell(r, 4, d)
        if r in (10, 11, 12, 18, 19, 22, 25, 5, 6, 7): x.fill = YFILL
    bd['C25'].number_format = '0%'; bd['C11'].number_format = 'yyyy-mm-dd'; bd['C13'].number_format = 'yyyy-mm-dd'
    bd.cell(27, 1, 'الخلايا الصفراء مُدخلة وقابلة للتعديل، والبيضاء محسوبة تلقائياً.').font = Font(name='Arial', size=9, italic=True)
    for col, w in zip('ABCD', (5, 52, 44, 12)): bd.column_dimensions[col].width = w
    # tables
    s1, rows1 = _table(wb, 'الكميات_الحالية', 'جدول الكميات 1 (الحالي) - %s - بلدة %s' % (tag, town), items, now, STD, 'كميات فقط. أسعار الوحدة تُدخل لاحقاً (من البرنامج أو الخلايا الصفراء) بعد اعتماد الدراسة الفنية.')
    s2, rows2 = _table(wb, 'الكميات_بعد_10_سنوات', 'جدول الكميات 2 (بعد %d سنوات) - %s - بلدة %s' % (G['years'], tag, town), items, y10, STD, 'المجموع الكلي في نهاية الاستثمار (الشبكة الحالية + التوسعات). الأسعار تُدخل في الجدول 1 ويمكن نسخها هنا.')
    for ws, hv in ((s1, hang_now), (s2, hang_10)):
        for i in range(5, ws.max_row + 1):
            if str(ws.cell(i, 2).value or '').startswith('مواد تعليق'):
                ws.cell(i, 5).value = ('=%s!B7' % INPUTS) if ws is s1 else hv
        # price of year-10 table links to table 1 prices
    for i in range(5, s2.max_row + 1):
        if s2.cell(i, 4).value and s2.cell(i, 2).value:
            s2.cell(i, 6).value = "=IF('الكميات_الحالية'!F%d=\"\",\"\",'الكميات_الحالية'!F%d)" % (i, i) if s1.cell(i, 2).value == s2.cell(i, 2).value else None
            s2.cell(i, 6).fill = PatternFill(fill_type=None)
    # inputs
    wi = wb.create_sheet(INPUTS); wi.sheet_view.rightToLeft = True
    wi['A1'] = 'مدخلات الدراسة (تُدخل بعد الدراسة الفنية)'; wi['A1'].font = Font(name='Arial', size=13, bold=True)
    _hdr(wi, 2, ['المدخل', 'القيمة', 'الوحدة', 'ملاحظة'])
    vals = {3: None, 4: '=B3', 5: 0, 6: 0, 7: hang_now}
    for lab, r, u, note in IN_ROWS:
        wi.cell(r, 1, lab); x = wi.cell(r, 2, vals[r]); x.fill = YFILL; wi.cell(r, 3, u); wi.cell(r, 4, note)
        for c in range(1, 5): wi.cell(r, c).border = BORDER; wi.cell(r, c).font = F_N
    for col, w in zip('ABCD', (36, 14, 10, 70)): wi.column_dimensions[col].width = w
    # assumptions
    wa = wb.create_sheet('الافتراضات'); wa.sheet_view.rightToLeft = True
    _hdr(wa, 1, ['الافتراض / Assumption', 'القيمة / Value', 'ملاحظة / Note'])
    A = [('المشتركون اليوم (مباني الدراسة)', G['subs0'], 'أساس نمو الكميات'), ('نمو المشتركين سنوياً', '%g%%' % (G['rate'] * 100), 'قابل للتعديل في study.json (growth)'),
         ('المدة (سنوات)', G['years'], ''), ('المشتركون بعد المدة', G['subs10'], ''), ('مشتركون لكل سبلتر فرعي', G['subs_per_secondary'], 'منفذان احتياط من 8'),
         ('سبلترات فرعية جديدة (صافي)', G['new_sec'], ''), ('سبلتر فرعي لكل رئيسي', G['secondaries_per_primary'], ''), ('سبلترات رئيسية جديدة (صافي)', G['new_prim'], ''),
         ('كلوجرات جديدة (صافي)', G['new_clo'], 'بنسبة اليوم لكل سبلتر رئيسي'), ('كبلات فرعية جديدة', 'بنسبة السبلترات الرئيسية الجديدة إلى الحالية', 'بنفس توزيع الأحجام'),
         ('كبلات رئيسية جديدة', 0, 'فرضية: السبلترات الجديدة على المسارات الرئيسية الحالية'), ('منافذ PON', 'سبلترات رئيسية + %d' % STD['pon']['extra_ports'], ''),
         ('الأسعار', 'فارغة', 'تُدخل من البرنامج بعد اعتماد الدراسة الفنية'), ('أشهر العمل', 'مدخل لكل دراسة', 'صفحة المدخلات')]
    for i, (a, b, c) in enumerate(A, 2):
        wa.cell(i, 1, a); wa.cell(i, 2, b); wa.cell(i, 3, c)
        for k in (1, 2, 3): wa.cell(i, k).border = BORDER; wa.cell(i, k).font = F_N
    for col, w in zip('ABC', (40, 36, 60)): wa.column_dimensions[col].width = w
    # financial summary
    sm = wb.create_sheet('الملخص_المالي'); sm.sheet_view.rightToLeft = True
    sm['A1'] = 'الملخص المالي - شبكة FTTH الهوائية - بلدة %s - %s' % (town, tag); sm['A1'].font = Font(name='Arial', size=13, bold=True)
    sm['A2'] = 'نطاق الدراسة ينتهي عند السبلترات الفرعية. الأرقام تُحدَّث تلقائياً من جدولي الكميات.'
    _hdr(sm, 3, ['البند', 'الحالي', 'بعد %d سنوات' % G['years'], 'الزيادة'])
    def ref(sheet, key): return "'%s'!E%d" % (sheet, (rows1 if sheet == 'الكميات_الحالية' else rows2)[key])
    k_p = next(k for k in rows1 if k.startswith('سبلتر 1:8 رئيسي')); k_s = next(k for k in rows1 if k.startswith('سبلتر 1:8 فرعي')); k_c = next(k for k in rows1 if k.startswith('كلوجر'))
    mains = [k for k in rows1 if k.startswith('كابل رئيسي')]; brs = [k for k in rows1 if k.startswith('كابل فرعي')]
    tot1 = max(rows1.values()); tr = next(i for i in range(5, s1.max_row + 1) if str(s1.cell(i, 1).value or '').startswith('الإجمالي (قبل'))
    S = [('المشتركون المستهدفون', "='بيانات العرض'!C19", '=ROUND(B4*(1+%g)^%d,0)' % (G['rate'], G['years'])),
         ('السبلترات الرئيسية 1:8 (مع احتياط)', '=' + ref('الكميات_الحالية', k_p), '=' + ref('الكميات_بعد_10_سنوات', k_p)),
         ('السبلترات الفرعية 1:8 (مع احتياط)', '=' + ref('الكميات_الحالية', k_s), '=' + ref('الكميات_بعد_10_سنوات', k_s)),
         ('الكلوجرات (مع احتياط)', '=' + ref('الكميات_الحالية', k_c), '=' + ref('الكميات_بعد_10_سنوات', k_c)),
         ('الكبلات الرئيسية (م، للطلب)', '=' + '+'.join(ref('الكميات_الحالية', k) for k in mains), '=' + '+'.join(ref('الكميات_بعد_10_سنوات', k) for k in mains)),
         ('الكبلات الفرعية (م، للطلب)', '=' + '+'.join(ref('الكميات_الحالية', k) for k in brs), '=' + '+'.join(ref('الكميات_بعد_10_سنوات', k) for k in brs)),
         ('الإجمالي قبل الهامش', "='الكميات_الحالية'!G%d" % tr, "='الكميات_بعد_10_سنوات'!G%d" % tr),
         ('نسبة الهامش', "='الكميات_الحالية'!G%d" % (tr + 1), "='الكميات_بعد_10_سنوات'!G%d" % (tr + 1)),
         ('الإجمالي مع الهامش', "='الكميات_الحالية'!G%d" % (tr + 2), "='الكميات_بعد_10_سنوات'!G%d" % (tr + 2))]
    for i, (a, b, c) in enumerate(S, 4):
        sm.cell(i, 1, a); sm.cell(i, 2, b); sm.cell(i, 3, c)
        if a != 'نسبة الهامش': sm.cell(i, 4, '=C%d-B%d' % (i, i))
        for k in (1, 2, 3, 4): sm.cell(i, k).border = BORDER; sm.cell(i, k).font = F_N
    sm.cell(13, 1, 'كلفة الاشتراك الواحد'); sm['B13'] = '=IF(B12="","",B12/B4)'; sm['C13'] = '=IF(C12="","",C12/C4)'
    sm['A15'] = 'الأسعار فارغة حتى تُدخل. الأرقام المالية تظهر بعد إدخال الأسعار.'
    for col, w in zip('ABCD', (44, 16, 16, 14)): sm.column_dimensions[col].width = w
    wb._sheets = [wb[n] for n in ('الملخص_المالي', 'الكميات_الحالية', 'الكميات_بعد_10_سنوات', INPUTS, 'بيانات العرض', 'الافتراضات')]
    wb.active = 0
    wb.save(path)

def create_templates(tool_dir, name, town, m, STD, g=None):
    """writes the two BOQ templates into tool_dir (study 'tool' folder) and returns their file names"""
    now, y10, G = quantities(m, STD, g)
    G = dict(G, **dict(GROWTH_DEFAULT, **(g or {})))
    names = []
    for kind, suf in (('real', 'عرض_حقيقي'), ('company', 'عرض_الشركة')):
        fn = 'FTTH_%s_BOQ_%s.xlsx' % (name, suf)
        create_workbook(os.path.join(tool_dir, fn), town, kind, now, y10, G, STD, m, y10['hang'] if False else now['hang'], y10['hang'])
        names.append(fn)
    return names

def refresh_workbook(path_in, path_out, m, STD, g=None):
    """generic studies: re-fill quantity cells from the (edited) design; prices, months, excavation and manholes already typed are kept."""
    from ftth_update import rows_by_label, find_row
    wb = openpyxl.load_workbook(path_in); now, y10, G = quantities(m, STD, g)
    for sh, q in (('الكميات_الحالية', now), ('الكميات_بعد_10_سنوات', y10)):
        ws = wb[sh]; rows = rows_by_label(ws)
        for r, t in rows.items():
            mt = re.match(r'(كابل رئيسي|كابل فرعي) (\d+)', t)
            key = None
            if mt: key = ('M' if mt.group(1) == 'كابل رئيسي' else 'B') + mt.group(2)
            elif t.startswith('سبلتر 1:8 رئيسي'): key = 'P'
            elif t.startswith('سبلتر 1:8 فرعي'): key = 'S'
            elif t.startswith('كلوجر'): key = 'C'
            elif t.startswith('بطاقة GPON'): key = 'gpon'
            elif t.startswith('موزع ألياف'): key = 'odf'
            elif t.startswith('Patch cord'): key = 'patch'
            elif t.startswith('صليب تخزين'): key = 'cross'
            if key and key in q: ws.cell(r, 5).value = q[key]
        newkeys = [k for k in q if re.match(r'[MB]\d+$', k) and q[k] > 0 and not any(re.match(r'(كابل رئيسي|كابل فرعي) %s ' % k[1:], t) and (t.startswith('كابل رئيسي') == (k[0] == 'M')) for t in rows.values())]
        if newkeys: print('تنبيه: أحجام كبلات جديدة بلا بند في %s: %s. أعد إنشاء القالب أو أضفها يدوياً.' % (sh, '، '.join(newkeys)))
    wb.save(path_out)
    return now, y10, G

# ---------------------------------------------------------------- prices (kept locally, never in the repo)
def _items(ws):
    from ftth_update import rows_by_label
    return rows_by_label(ws)

def prices_template(xlsx_real, out_json):
    """writes الأسعار.json with every item label and an empty price for both offers"""
    wb = openpyxl.load_workbook(xlsx_real); labels = list(_items(wb['الكميات_الحالية']).values())
    d = {'_note': 'أدخل سعر الوحدة بالدولار لكل بند. اترك null لما لم يُسعَّر بعد. real = العرض الحقيقي، company = عرض الشركة', 'real': {l: None for l in labels}, 'company': {l: None for l in labels}}
    json.dump(d, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return d

def extract_prices(xlsx):
    """reads unit prices from an existing priced BOQ workbook (to reuse them in a new study)"""
    wb = openpyxl.load_workbook(xlsx); ws = wb['الكميات_الحالية']
    return {t: ws.cell(r, 6).value for r, t in _items(ws).items() if isinstance(ws.cell(r, 6).value, (int, float))}

def apply_prices(xlsx_in, xlsx_out, prices):
    """prices = {label: price}. Writes column F of the current table and the year-10 table (matched by label)."""
    wb = openpyxl.load_workbook(xlsx_in); n = 0
    for sh in ('الكميات_الحالية', 'الكميات_بعد_10_سنوات'):
        ws = wb[sh]
        for r, t in _items(ws).items():
            if sh == 'الكميات_بعد_10_سنوات' and isinstance(ws.cell(r, 6).value, str) and ws.cell(r, 6).value.startswith('='): continue
            p = prices.get(t)
            if isinstance(p, (int, float)): ws.cell(r, 6).value = p; n += 1
    wb.save(xlsx_out)
    return n

def priced_total(xlsx):
    wb = openpyxl.load_workbook(xlsx); ws = wb['الكميات_الحالية']
    return sum(1 for r, t in _items(ws).items() if isinstance(ws.cell(r, 6).value, (int, float)))


def calibrate(root):
    import ftth_std, glob, openpyxl
    for s in ('Orem', 'Bleon', 'Ihsem'):
        d = os.path.join(root, s + '_10y', 'أداة_التحديث'); j = json.load(open(os.path.join(d, 'study.json'), encoding='utf-8'))
        STD = ftth_std.load(j, os.path.join(root, '..'))
        now, y10, G = quantities(j['baseline'], STD)
        wb = openpyxl.load_workbook(glob.glob(d + '/*حقيقي.xlsx')[0])
        print('==', s, {k: G[k] for k in ('subs0', 'subs10', 'new_sec', 'new_prim', 'new_clo')})
        for sh, q in (('الكميات_الحالية', now), ('الكميات_بعد_10_سنوات', y10)):
            ws = wb[sh]; row = {}
            for r in range(5, 45):
                b = ws.cell(r, 2).value
                if b: row[str(b).split('\n')[0]] = ws.cell(r, 5).value
            def g(pref):
                for k, v in row.items():
                    if k.startswith(pref): return v
            cmp = []
            for key, pref in [('P', 'سبلتر 1:8 رئيسي'), ('S', 'سبلتر 1:8 فرعي'), ('C', 'كلوجر'), ('gpon', 'بطاقة GPON'), ('odf', 'موزع'), ('patch', 'Patch'), ('cross', 'صليب'), ('hang', 'مواد تعليق')]:
                cmp.append((key, q[key], g(pref)))
            for key in sorted(k for k in q if re.match(r'[MB]\d+$', k)):
                pref = ('كابل رئيسي ' if key[0] == 'M' else 'كابل فرعي ') + key[1:] + ' '
                cmp.append((key, q[key], g(pref)))
            bad = [c for c in cmp if c[1] != c[2]]
            print(sh, 'OK' if not bad else 'DIFF', bad)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='BOQ عام: أسعار')
    sub = ap.add_subparsers(dest='cmd')
    a1 = sub.add_parser('prices-template'); a1.add_argument('--boq', required=True); a1.add_argument('--out', required=True)
    a2 = sub.add_parser('apply-prices'); a2.add_argument('--boq', required=True); a2.add_argument('--prices', required=True); a2.add_argument('--offer', choices=['real', 'company'], default='real'); a2.add_argument('--out')
    a3 = sub.add_parser('calibrate'); a3.add_argument('root')
    a = ap.parse_args()
    if a.cmd == 'prices-template': prices_template(a.boq, a.out); print('كتبت', a.out)
    elif a.cmd == 'apply-prices':
        pr = {k: v for k, v in json.load(open(a.prices, encoding='utf-8')).get(a.offer, {}).items() if isinstance(v, (int, float))}
        print('طُبّقت أسعار على', apply_prices(a.boq, a.out or a.boq, pr), 'بند')
    elif a.cmd == 'calibrate': calibrate(a.root)
    else: ap.print_help()
