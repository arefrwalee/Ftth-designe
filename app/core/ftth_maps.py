# -*- coding: utf-8 -*-
"""خرائط PDF عامة من أي gpkg (صفحتان: الكبلات الرئيسية بحسب السعة، والفرعية بحسب مجموعة الرئيسي).
تحتاج matplotlib؛ إن لم يكن مثبتاً تُتخطى الخطوة برسالة. العناوين العربية تمر عبر ftth_ar لتظهر متصلة.
هذه خرائط نظرة عامة بلا خلفية صور؛ الخرائط التفصيلية على الستاليت تُطبع من تخطيطات مشروع QGIS."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ftth_ar
from ftth_update import read_gpkg

CORE_COLOR = {4: '#7a7a7a', 8: '#2e7d32', 12: '#1565c0', 24: '#ef6c00', 48: '#c62828', 72: '#6a1b9a', 96: '#00838f', 144: '#4e342e', 288: '#000000'}


def build(gpkg, out_pdf, town, log=print):
    try:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.lines import Line2D
    except Exception:
        log('matplotlib غير مثبت: تُخطّى خرائط PDF (ثبّته بـ pip install matplotlib)'); return None
    ar = lambda s: ftth_ar.visual(ftth_ar.shape(s))
    d = read_gpkg(gpkg)
    def lines(g):
        return list(g.geoms) if g.geom_type.startswith('Multi') else [g]
    roads = [l for r in d.get('مسارات_الطرق', []) for l in lines(r['geometry'])]
    M = d.get('الكوابل_الرئيسية', []); B = d.get('الكوابل_الفرعية', [])
    PR = d.get('السبلترات_الرئيسية', []); C = d.get('المركز', [])
    def base(ax):
        for l in roads:
            x, y = l.xy; ax.plot(x, y, color='#d0d0d0', lw=0.6, zorder=1)
        ax.set_aspect('equal'); ax.axis('off')
    with PdfPages(out_pdf) as pdf:
        fig, ax = plt.subplots(figsize=(16.5, 11.7)); base(ax)
        for c in sorted(M, key=lambda r: r['Cores']):
            x, y = c['geometry'].xy; ax.plot(x, y, color=CORE_COLOR.get(int(c['Cores']), '#000'), lw=0.8 + int(c['Cores']) ** 0.5 / 3, zorder=3)
        for p in PR:
            ax.plot(p['geometry'].x, p['geometry'].y, 'o', ms=5, color='#1a237e', zorder=5)
            ax.annotate(p['Primary_ID'], (p['geometry'].x, p['geometry'].y), fontsize=6, xytext=(3, 3), textcoords='offset points', zorder=6)
        for c in C: ax.plot(c['geometry'].x, c['geometry'].y, 's', ms=10, color='#b71c1c', zorder=7)
        cs = sorted({int(c['Cores']) for c in M})
        ax.legend(handles=[Line2D([0], [0], color=CORE_COLOR.get(k, '#000'), lw=2, label='%d ألياف' % k if False else '%d fibres' % k) for k in cs], loc='lower left')
        ax.set_title(ar('%s — الكبلات الرئيسية (بحسب عدد الألياف)' % town), fontsize=14); pdf.savefig(fig); plt.close(fig)
        fig, ax = plt.subplots(figsize=(16.5, 11.7)); base(ax)
        col = {p['Primary_ID']: p.get('Group_Colour') or '#444' for p in PR}
        for c in B:
            x, y = c['geometry'].xy; ax.plot(x, y, color=col.get(c.get('Group_ID'), '#444'), lw=1.2, zorder=3)
        for s in d.get('السبلترات_الفرعية', []):
            ax.plot(s['geometry'].x, s['geometry'].y, 'o', ms=2.5, color=s.get('Group_Colour') or '#444', zorder=4)
        for p in PR:
            ax.plot(p['geometry'].x, p['geometry'].y, 'o', ms=6, color='k', zorder=5)
        ax.set_title(ar('%s — الشبكة الفرعية (لون لكل سبلتر رئيسي)' % town), fontsize=14); pdf.savefig(fig); plt.close(fig)
    log('PDF: ' + out_pdf); return out_pdf


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--gpkg', required=True); ap.add_argument('--town', required=True); ap.add_argument('--out')
    a = ap.parse_args()
    build(a.gpkg, a.out or os.path.splitext(a.gpkg)[0] + '_خرائط.pdf', a.town)
