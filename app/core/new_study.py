# -*- coding: utf-8 -*-
"""دراسة جديدة: ينشئ مجلد أداة التحديث لبلدة جديدة انطلاقاً من دراسة مرجعية.

الاستعمال:
  python new_study.py --name Salqin --town "سلقين" --gpkg C:\\...\\FTTH_Salqin.gpkg --from C:\\...\\Orem_10y\\أداة_التحديث [--out C:\\...]

ما يفعله:
  1) ينسخ قوالب BOQ من الدراسة المرجعية ويبدّل اسم البلدة فيها.
  2) يكتب study.json: baseline = baseline المرجع، فتصبح الكميات الناتجة = كميات المرجع + (f(جديد) - f(مرجع)).
     هذه *تقدير أولي* من دراسة مرجعية وليست BOQ مصمَّماً من الصفر: البنود التي لا تُشتق من الـ gpkg
     (غرفة المقسم، الطاقة، المتفرقات، الأشهر، المحروقات، الحفر، المشتركون المستهدفون) تبقى كما في المرجع وتحتاج مراجعتك.
  3) يقارن مقاييس الـ gpkg الجديد بالمرجع ويطبعها.
"""
import sys, os, json, shutil, argparse, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openpyxl
import ftth_std
from ftth_update import read_gpkg, metrics, STD

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', help='اسم لاتيني قصير للدراسة (يُستعمل في أسماء الملفات)')
    ap.add_argument('--town', help='اسم البلدة بالعربية')
    ap.add_argument('--gpkg', help='ملف GeoPackage للدراسة الجديدة')
    ap.add_argument('--from', dest='ref', help='مجلد أداة_التحديث لدراسة مرجعية (فيه study.json)')
    ap.add_argument('--out', default=None, help='المجلد الذي يُنشأ فيه <Name>_10y (الافتراضي: بجوار المرجع)')
    a = ap.parse_args()
    import ftth_ar; ftth_ar.install(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'standards', 'aerial_default.json'), encoding='utf-8')).get('console', {}).get('arabic_shaping', 'auto'))
    ask = lambda q: (print(q, end=' ', flush=True), input().strip().strip('"'))[1]
    if not a.name: a.name = ask('اسم لاتيني قصير للدراسة (مثال Salqin):')
    if not a.town: a.town = ask('اسم البلدة بالعربية:')
    if not a.gpkg: a.gpkg = ask('مسار ملف gpkg الجديد (اسحب الملف إلى هنا):')
    if not a.ref: a.ref = ask('مسار مجلد أداة_التحديث للدراسة المرجعية (اسحب المجلد إلى هنا):')
    ref = os.path.abspath(a.ref); rc = json.load(open(os.path.join(ref, 'study.json'), encoding='utf-8'))
    pkg = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    root = os.path.abspath(a.out) if a.out else os.path.abspath(os.path.join(ref, '..', '..'))
    sdir = os.path.join(root, '%s_10y' % a.name); tool = os.path.join(sdir, 'أداة_التحديث')
    if os.path.exists(os.path.join(tool, 'study.json')): sys.exit('الدراسة موجودة مسبقاً: ' + tool)
    os.makedirs(tool, exist_ok=True)
    file_town = a.town.strip().replace(' ', '_'); gp_name = 'FTTH_%s.gpkg' % a.name
    shutil.copy(a.gpkg, os.path.join(sdir, gp_name))
    # templates: rename + replace the town name inside the text cells
    tpls = []
    for t in rc['templates']:
        nt = t.replace('FTTH_%s_' % rc['study'], 'FTTH_%s_' % a.name)
        wb = openpyxl.load_workbook(os.path.join(ref, t)); n = 0
        for ws in wb:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and rc['town_ar'] in c.value and not c.value.startswith('='):
                        c.value = c.value.replace(rc['town_ar'], a.town); n += 1
        wb.save(os.path.join(tool, nt)); tpls.append(nt); print('قالب:', nt, '(استُبدل اسم البلدة في %d خلية)' % n)
    cfg = dict(rc); cfg.update(study=a.name, town_ar=a.town, file_town=file_town, gpkg=gp_name, templates=tpls,
                              derived_from=dict(study=rc['study'], note='baseline منسوخ من المرجع: الكميات تقدير أولي حتى تُراجَع البنود غير المشتقة من الـ gpkg'))
    json.dump(cfg, open(os.path.join(tool, 'study.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'تحديث.bat.template'), os.path.join(tool, 'تحديث.bat'))
    # compare metrics
    ftth_std.load(cfg, pkg)
    me = metrics(read_gpkg(os.path.join(sdir, gp_name))); mb = rc['baseline']
    print('\nمقاييس الدراسة الجديدة مقابل المرجع (%s):' % rc['study'])
    for k in ('Mord', 'Bord', 'KP', 'K', 'NC', 'PON', 'ODF', 'pol', 'subs'):
        print('  %-5s جديد %10.1f   مرجع %10.1f' % (k, me.get(k, 0), mb.get(k, 0)))
    print('\nتم إنشاء:', tool)
    print('مواد التعليق: أدخل الكمية بنفسك في بند مواد التعليق (الكميات_الحالية والكميات_بعد_10_سنوات) في القالبين؛ الرقم المنسوخ هو رقم المرجع وليس رقم هذه البلدة.')
    print('الخطوة التالية: شغّل تحديث.bat داخل هذا المجلد، وراجع البنود غير المشتقة من الـ gpkg (غرفة المقسم، الطاقة، المتفرقات، الأشهر، المحروقات، الحفر، المشتركون المستهدفون).')

if __name__ == '__main__': main()
