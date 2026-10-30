# -*- coding: utf-8 -*-
"""Google Earth KML/KMZ from the GeoPackage layers (UTM 37N -> WGS84, no pyproj needed)."""
import math, os, zipfile
from xml.sax.saxutils import escape
from shapely.ops import unary_union
from ftth_update import L, num
from ftth_std import STD, LAY

def to_lonlat(x, y, zone=None):
    zone = zone or STD['crs']['utm_zone']
    a = 6378137.0; f = 1 / 298.257223563; k0 = 0.9996; e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x -= 500000.0; M = y / k0; mu = M / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    N1 = a / math.sqrt(1 - e2 * math.sin(phi) ** 2); T1 = math.tan(phi) ** 2; C1 = ep2 * math.cos(phi) ** 2
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi) ** 2) ** 1.5; D = x / (N1 * k0)
    lat = phi - (N1 * math.tan(phi) / R1) * (D ** 2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * ep2) * D ** 4 / 24 + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * ep2 - 3 * C1 ** 2) * D ** 6 / 720)
    lon = (D - (1 + 2 * T1 + C1) * D ** 3 / 6 + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * ep2 + 24 * T1 ** 2) * D ** 5 / 120) / math.cos(phi)
    return math.degrees(lon) + (zone * 6 - 183), math.degrees(lat)

def kc(h, a=255):
    h = h.lstrip('#'); return '%02x%s%s%s' % (a, h[4:6], h[2:4], h[0:2])
COL = {96: '#6A1B9A', 48: '#C8102E', 24: '#FF7F00', 12: '#D20096', 8: '#1E64E6', 4: '#009650'}
WM = {96: 8, 4: 3, 8: 4, 12: 5, 24: 6, 48: 7}; WB = {4: 2, 8: 3, 12: 4, 24: 5}
SH = 'http://maps.google.com/mapfiles/kml/shapes/'
PAL = ['#00897B', '#8D5524', '#7B1FA2', '#E65100', '#C2185B', '#1565C0', '#558B2F', '#455A64', '#AD1457', '#6D4C41']
pk = lambda r: str(r.get('Primary_ID') or r.get('Group_ID') or '')

def _coords(g):
    return ' '.join('%.7f,%.7f,0' % to_lonlat(x, y) for x, y, *_ in g.coords)
def _desc(rows): return '<![CDATA[' + '<br/>'.join('<b>%s:</b> %s' % (k, v) for k, v in rows if v not in (None, '')) + ']]>'
def _fold(n, items, op=1): return '<Folder><name>%s</name><open>%d</open>' % (escape(n), op) + ''.join(items) + '</Folder>'

class Kml:
    def __init__(self, layers, town):
        self.ly = layers; self.town = town; self.sty = []
        P = L(layers, LAY['primary_splitters']); self.gc = {}
        for i, p in enumerate(sorted(P, key=lambda r: r['Primary_ID'])):
            c = str(p.get('Group_Colour') or '').strip()
            self.gc[p['Primary_ID']] = c if c.startswith('#') and len(c) == 7 else PAL[i % len(PAL)]
        for c, h in COL.items(): self.style('m%d' % c, line=(h, WM.get(c, 4)))
        for p, h in self.gc.items():
            for c in WB: self.style('b_%s_%d' % (p, c), line=(h, WB[c]))
            self.style('sec_%s' % p, icon=(h, 0.8, SH + 'placemark_circle.png', 0.55))
        for c in WB: self.style('bm_%d' % c, line=('#222222', WB[c]))
        self.style('prim', icon=('#0F1750', 1.1, SH + 'square.png', 0.9)); self.style('co', icon=('#008C00', 1.6, SH + 'star.png', 1.0))
        self.style('c_main', icon=('#E53935', 0.5, SH + 'diamond.png', 0)); self.style('c_br', icon=('#FFCD00', 0.5, SH + 'diamond.png', 0)); self.style('c_mrg', icon=('#00ACC1', 0.55, SH + 'triangle.png', 0))
        self.cs = {'تفرع رئيسي': 'c_main', 'تفرع فرعي': 'c_br', 'دمج/فصل': 'c_mrg'}
    def style(self, sid, line=None, icon=None):
        x = '<Style id="%s">' % sid
        if line: x += '<LineStyle><color>%s</color><width>%s</width></LineStyle>' % (kc(line[0]), line[1])
        if icon: x += '<IconStyle><color>%s</color><scale>%s</scale><Icon><href>%s</href></Icon></IconStyle><LabelStyle><scale>%s</scale></LabelStyle>' % (kc(icon[0]), icon[1], icon[2], icon[3])
        self.sty.append(x + '</Style>')
    def sid(self, p, c): return 'b_%s_%d' % (p, c) if ('b_%s_%d' % (p, c)) in ''.join(self.sty) else 'bm_%d' % (c if c in WB else 4)
    def line(self, r, sid, extra=()):
        g = r['geometry']
        if g is None: return ''
        parts = ''.join('<LineString><tessellate>1</tessellate><coordinates>%s</coordinates></LineString>' % _coords(l) for l in (g.geoms if g.geom_type.startswith('Multi') else [g]))
        if g.geom_type.startswith('Multi'): parts = '<MultiGeometry>' + parts + '</MultiGeometry>'
        return '<Placemark><name>%s</name><styleUrl>#%s</styleUrl><description>%s</description>%s</Placemark>' % (escape(str(r.get('Cable_ID'))), sid, _desc([('عدد الألياف', r.get('Cores')), ('المستعمل', r.get('Used')), ('الطول (م)', r.get('Length_m')), ('طول الطلب (م)', r.get('Order_m'))] + list(extra)), parts)
    def pt(self, name, sid, g, rows):
        if g is None: return ''
        lo, la = to_lonlat(g.x, g.y)
        return '<Placemark><name>%s</name><styleUrl>#%s</styleUrl><description>%s</description><Point><coordinates>%.7f,%.7f,0</coordinates></Point></Placemark>' % (escape(str(name)), sid, _desc(rows), lo, la)
    def clo(self, r):
        return self.pt(r.get('Closure_ID'), self.cs.get(r.get('Type'), 'c_br'), r['geometry'], [('النوع', r.get('Type')), ('الكبلات', r.get('Cables')), ('الألياف المستعملة', r.get('Used_Fibres')), ('اللحامات', r.get('Splices'))])
    def head(self, name, g, rng):
        lo, la = to_lonlat(g.x, g.y)
        return '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>%s</name><LookAt><longitude>%.6f</longitude><latitude>%.6f</latitude><range>%d</range><tilt>0</tilt></LookAt>' % (escape(name), lo, la, rng) + ''.join(self.sty)
    def prim_pt(self, p):
        return self.pt(p['Primary_ID'], 'prim', p['geometry'], [('المجموعة', p['Primary_ID']), ('المنافذ المستعملة', p.get('Used_Ports')), ('الاحتياط', p.get('Spare_Ports')), ('المشتركون', p.get('Subscribers')), ('منفذ PON', p.get('PON_Port'))])
    def sec_pt(self, s, p):
        return self.pt('%s · %s' % (s['Secondary_ID'], p), 'sec_%s' % p, s['geometry'], [('المجموعة', p), (LAY['buildings'], s.get('Buildings', s.get('Used_Ports'))), ('الاحتياط', s.get('Spare_Ports'))])

def build_all(layers, town, outdir, prefix):
    k = Kml(layers, town); co = L(layers, LAY['center'])[0]['geometry']
    P = sorted(L(layers, LAY['primary_splitters']), key=lambda r: r['Primary_ID']); S = L(layers, LAY['secondary_splitters'])
    M = L(layers, LAY['main_cables']); B = L(layers, LAY['branch_cables'])
    clos = [r for n in (LAY['closure_main'], LAY['closure_branch'], LAY['closure_merge']) for r in L(layers, n)]
    merged = lambda r: str(r.get('Merged')) == 'نعم' or '+' in pk(r)
    mainf = _fold('الكوابل الرئيسية', [k.line(r, 'm%d' % int(num(r.get('Cores'))), [('الكبل الموازي', r.get('Run')), ('فئة الطريق', r.get('Road_Class'))]) for r in M], 0)
    cof = _fold(LAY['center'], [k.pt('المركز OLT', 'co', co, [('الوصف', 'المقسم المركزي')])])
    clof = _fold('كلوجرات التوصيل', [_fold('%s (%d)' % (t, sum(1 for r in clos if r.get('Type') == t)), [k.clo(r) for r in clos if r.get('Type') == t]) for t in ('تفرع رئيسي', 'تفرع فرعي', 'دمج/فصل')])
    def gfold(p):
        pid = p['Primary_ID']; own = [r for r in B if pk(r) == pid and not merged(r)]
        it = [k.prim_pt(p)] + [k.sec_pt(s, pid) for s in S if pk(s) == pid] + [k.line(r, k.sid(pid, int(num(r.get('Cores')))), [('المجموعة', pid)]) for r in own]
        return _fold('مجموعة %s' % pid, it, 0)
    grp = _fold('المجموعات (سبلتر رئيسي + سبلتراته الفرعية + كوابله الخاصة)', [gfold(p) for p in P], 0)
    mg = _fold('كوابل فرعية مدمجة لعدة مجموعات', [k.line(r, 'bm_%d' % (int(num(r.get('Cores'))) if int(num(r.get('Cores'))) in WB else 4), [('المجموعات', pk(r))]) for r in B if merged(r)], 0)
    kml = k.head('%s - شبكة FTTH' % town, co, 3500) + mainf + grp + mg + clof + cof + '</Document></kml>'
    open(os.path.join(outdir, '%s_FTTH_GoogleEarth.kml' % prefix), 'w', encoding='utf-8').write(kml)
    # sectors
    sd = os.path.join(outdir, 'sectors_kml'); os.makedirs(sd, exist_ok=True)
    for f in os.listdir(sd): os.remove(os.path.join(sd, f))
    allsec = []
    for p in P:
        pid = p['Primary_ID']; sec = [s for s in S if pk(s) == pid]; br = [r for r in B if pid in pk(r).split('+')]
        ub = unary_union([r['geometry'] for r in br if r['geometry'] is not None]) if br else None
        mn = [r for r in M if r['geometry'] is not None and p['geometry'] is not None and r['geometry'].distance(p['geometry']) < 6]
        cl = [r for r in clos if ub is not None and r['geometry'] is not None and r['geometry'].distance(ub) < 3]
        parts = []
        if mn: parts.append(_fold('الكبل الرئيسي المغذّي', [k.line(r, 'm%d' % int(num(r.get('Cores'))), [('الكبل الموازي', r.get('Run'))]) for r in mn], 1))
        parts.append(_fold('الكوابل الفرعية', [k.line(r, ('bm_%d' % (int(num(r.get('Cores'))) if int(num(r.get('Cores'))) in WB else 4)) if '+' in pk(r) else k.sid(pid, int(num(r.get('Cores')))), [('السبلتر الرئيسي', pk(r))]) for r in br], 1))
        parts.append(_fold('السبلتر الرئيسي', [k.prim_pt(p)], 1)); parts.append(_fold('السبلترات الفرعية', [k.sec_pt(s, pid) for s in sec], 1)); parts.append(_fold('الكلوجرات', [k.clo(r) for r in cl], 1))
        x = k.head('%s - قطاع %s' % (town, pid), p['geometry'], 450) + ''.join(parts) + '</Document></kml>'
        with zipfile.ZipFile(os.path.join(sd, '%s_قطاع_%s.kmz' % (prefix, pid)), 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('doc.kml', x)
        allsec.append(_fold('قطاع %s' % pid, parts, 0))
    with zipfile.ZipFile(os.path.join(outdir, '%s_قطاعات_GoogleEarth.zip' % prefix), 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(sd)): z.write(os.path.join(sd, f), f)
    comb = k.head('%s - القطاعات' % town, co, 3500) + ''.join(allsec) + '</Document></kml>'
    open(os.path.join(outdir, '%s_القطاعات_طبقات.kml' % prefix), 'w', encoding='utf-8').write(comb)
    with zipfile.ZipFile(os.path.join(outdir, '%s_القطاعات_طبقات.kmz' % prefix), 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('doc.kml', comb)
    return len(P)
