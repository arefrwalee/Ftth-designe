# -*- coding: utf-8 -*-
"""«دراسة كاملة»: من gpkg فيه المباني والطرق والمركز (+الأعمدة اختيارياً) إلى دراسة جاهزة للمراجعة:
   1) مسودة التصميم (+طبقة أعمدة: من المسح أو مقترحة)   2) مجلد دراسة جديد من قوالب دراسة مرجعية
   3) حساب أولي (BOQ وعرض السعر...)   4) مشروع QGIS.
النتيجة تقدير أولي؛ بعد مراجعتك في QGIS يُعاد «تحديث الدراسة» فقط."""
import sys, os, json, shutil, subprocess, argparse, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ftth_std, ftth_design, ftth_qgis

PKG = os.path.abspath(os.path.join(HERE, '..'))


def py_script(script, args):
    """يشغّل سكربت من core بنفس مفسّر بايثون ويمرّر مخرجاته مباشرة."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', FTTH_AR='0')
    p = subprocess.Popen([sys.executable, '-u', os.path.join(HERE, script)] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL)
    for raw in p.stdout: print(raw.decode('utf-8', 'replace').rstrip('\r\n'), flush=True)
    return p.wait()


def _generic_study(out_root, name, town, gpkg, log):
    """مجلد دراسة جديد بقالب BOQ عام (مكونات فقط، بلا أسعار) يُملأ من التصميم نفسه."""
    import ftth_boq
    from ftth_update import read_gpkg, metrics
    STD = ftth_std.load({'standards': 'aerial_default', 'overrides': {}}, PKG)
    sdir = os.path.join(out_root, '%s_10y' % name); tool = os.path.join(sdir, 'أداة_التحديث'); os.makedirs(tool, exist_ok=True)
    gp_name = 'FTTH_%s.gpkg' % name; shutil.copy(gpkg, os.path.join(sdir, gp_name))
    m = metrics(read_gpkg(os.path.join(sdir, gp_name)))
    tpls = ftth_boq.create_templates(tool, name, town, m, STD)
    ftth_boq.prices_template(os.path.join(tool, tpls[0]), os.path.join(tool, 'الأسعار.json'))
    cfg = dict(study=name, town_ar=town, file_town=town.strip().replace(' ', '_'), gpkg=gp_name, templates=tpls, baseline=m, standards='aerial_default',
               overrides={}, generic=True, growth={}, reference='قالب BOQ عام: المكونات فقط، الأسعار والأشهر تُدخل لاحقاً. الكميات تُحسب من التصميم.')
    json.dump(cfg, open(os.path.join(tool, 'study.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    shutil.copy(os.path.join(HERE, 'تحديث.bat.template'), os.path.join(tool, 'تحديث.bat'))
    log('   قالب BOQ عام: %s' % '، '.join(tpls))
    return sdir, tool


def run(inp, name, town, ref_tool=None, out_root='.', poles_file=None, log=print):
    out_root = os.path.abspath(out_root)
    rc = None
    if ref_tool:
        ref_tool = os.path.abspath(ref_tool); rc = json.load(open(os.path.join(ref_tool, 'study.json'), encoding='utf-8')); ftth_std.load(rc, PKG)
    else: ftth_std.load({'standards': 'aerial_default', 'overrides': {}}, PKG)
    sdir = os.path.join(out_root, '%s_10y' % name)
    if os.path.exists(sdir): raise SystemExit('المجلد موجود مسبقاً: ' + sdir)
    tmp = os.path.join(out_root, '_draft_tmp_%s' % name)
    log('== 1/4 توليد مسودة التصميم'); t0 = time.time()
    out, stats, issues = ftth_design.generate(inp, tmp, ftth_std.STD, log=log)
    log('   %d سبلتر فرعي، %d رئيسي، كبلات %d م، أعمدة %d (%s)، ملاحظات %d' % (
        stats['secondaries'], stats['primaries'], stats['sub_m'] + stats['main_m'], stats['poles'], stats['poles_source'], stats['issues']))
    if rc:
        log('== 2/4 إنشاء مجلد الدراسة من قوالب %s' % rc.get('town_ar', rc['study']))
        code = py_script('new_study.py', ['--name', name, '--town', town, '--gpkg', out, '--from', ref_tool, '--out', out_root])
        if code != 0: raise SystemExit('فشل إنشاء الدراسة')
    else:
        log('== 2/4 إنشاء مجلد الدراسة (قالب BOQ عام)')
        sdir, _ = _generic_study(out_root, name, town, out, log)
    shutil.move(tmp, os.path.join(sdir, 'مسودة_المولد'))
    tool = os.path.join(sdir, 'أداة_التحديث')
    log('== 3/4 الحساب الأولي (BOQ وعرض السعر)')
    args = ['--study', tool] + (['--poles', poles_file] if poles_file else [])
    code = py_script('ftth_update.py', args)
    if code != 0: log('   توقف الحساب (راجع الأخطاء أعلاه). أصلحها في QGIS ثم شغّل «تحديث الدراسة».')
    log('== 4/4 مشروع QGIS')
    gp = os.path.join(sdir, 'FTTH_%s.gpkg' % name)
    q, gone, added = ftth_qgis.build(gp, sdir, town, 'FTTH %s' % town, log=log)
    log('تم. المجلد: %s' % sdir)
    return sdir


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True); ap.add_argument('--name', required=True); ap.add_argument('--town', required=True)
    ap.add_argument('--from', dest='ref', default=None, help='اختياري: مجلد أداة_التحديث لدراسة مرجعية (بدونه يُستعمل قالب BOQ عام)'); ap.add_argument('--out', required=True)
    ap.add_argument('--poles', help='ملف أعمدة المسح (CSV أو gpkg) اختياري')
    a = ap.parse_args(argv)
    run(a.input, a.name, a.town, a.ref, a.out, a.poles)


if __name__ == '__main__':
    main()
