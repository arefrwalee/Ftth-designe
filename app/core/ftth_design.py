# -*- coding: utf-8 -*-
"""مولّد الشبكة (المرحلة 3): مباني + طرق + موقع المركز  ->  مسودة gpkg بنفس مخطط الدراسات.

الخوارزمية (حتمية، بلا بحث عشوائي، بلا حلقات مفتوحة):
 1. شبكة الطرق: تُعقَّد التقاطعات ويُقسَّم كل مقطع عند أقرب نقطة لكل مبنى.
 2. المباني -> سبلترات فرعية: مكوّنات متصلة (فجوة <= component_gap) ثم تقسيم ثنائي متكرر
    حتى (عدد <= max_buildings و نصف القطر <= max_radius). موقع السبلتر = عقدة الطريق الأقل
    مجموع مسافات طرق للمباني.
 3. السبلترات الفرعية -> رئيسية: بنفس الطريقة (max_secondaries).
 4. الكبلات: شجرة أقصر المسارات على الطرق (من السبلتر الرئيسي لفرعياته، ومن المركز لرئيسياته)،
    تُقطَّع عند التفرعات، والسعة = أصغر حجم قياسي يغطي ceil(used*growth).
 5. الكلوجرات عند التفرعات.
المخرجات مسودة تحتاج مراجعة بشرية في QGIS، لا تصميماً نهائياً.
"""
import sys, os, math, json, heapq, sqlite3, struct, time, shutil, zipfile, re
from collections import defaultdict
import numpy as np
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import unary_union, substring
from shapely.strtree import STRtree
from shapely import wkb as _wkb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ftth_std
import ftth_update as U

PALETTE = ['#C61010', '#1565C0', '#2E7D32', '#EF6C00', '#6A1B9A', '#00838F', '#AD1457', '#5D4037',
           '#455A64', '#9E9D24', '#283593', '#BF360C']

DEFAULT_DESIGN = {
    "secondary": {"max_buildings": 6, "max_radius_m": 120.0, "component_gap_m": 80.0},
    "primary": {"max_secondaries": 6, "max_radius_m": 250.0, "component_gap_m": 200.0},
    "cable_sizing": {"branch_sizes": [4, 8, 12, 24, 48], "main_sizes": [4, 8, 12, 24, 48, 72, 96, 144, 288],
                     "growth": 1.62, "main_strict": True},
    "snap_pole_m": 30.0,
    "max_refine_rounds": 3,
    "max_seconds": 300,
}


def dget(STD):
    d = json.loads(json.dumps(DEFAULT_DESIGN))
    for k, v in (STD.get('design') or {}).items():
        if isinstance(v, dict) and isinstance(d.get(k), dict): d[k].update(v)
        else: d[k] = v
    return d


# ---------------------------------------------------------------- road graph
class Graph:
    def __init__(self):
        self.adj = defaultdict(list)   # node -> [(nbr, w, eid)]
        self.edges = []                # eid -> LineString (oriented a->b), a, b
        self.key2n = {}
        self.xy = []

    def node(self, x, y):
        k = (round(x, 1), round(y, 1))
        n = self.key2n.get(k)
        if n is None:
            n = len(self.xy); self.key2n[k] = n; self.xy.append((x, y))
        return n

    def add_edge(self, a, b, geom):
        if a == b or geom.length <= 0: return
        eid = len(self.edges); self.edges.append((geom, a, b))
        w = geom.length
        self.adj[a].append((b, w, eid)); self.adj[b].append((a, w, eid))

    def dijkstra(self, src, cutoff=None):
        dist = {src: 0.0}; pred = {}; pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, 1e18): continue
            if cutoff is not None and d > cutoff: break
            for v, w, eid in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, 1e18):
                    dist[v] = nd; pred[v] = (u, eid); heapq.heappush(pq, (nd, v))
        return dist, pred


def build_graph(road_geoms, snap_points):
    lines = []
    for g in road_geoms:
        if g is None: continue
        lines += list(g.geoms) if g.geom_type.startswith('Multi') else [g]
    noded = unary_union(lines)
    segs = list(noded.geoms) if noded.geom_type.startswith('Multi') else [noded]
    segs = [s for s in segs if s.geom_type == 'LineString' and s.length > 0]
    tree = STRtree(segs)
    cuts = defaultdict(list); snap = []
    for p in snap_points:
        i = int(tree.nearest(p)); s = segs[i]
        d = s.project(p); cuts[i].append(d)
        snap.append((i, d, s.interpolate(d), p.distance(s)))
    G = Graph(); segnodes = {}
    for i, s in enumerate(segs):
        ds = sorted(set([0.0, s.length] + [round(c, 2) for c in cuts.get(i, [])]))
        ds2 = [ds[0]]
        for d in ds[1:]:
            if d - ds2[-1] >= 0.5 or d == s.length: ds2.append(d)
        if ds2[-1] != s.length: ds2[-1] = s.length
        nl = []
        for a, b in zip(ds2[:-1], ds2[1:]):
            part = substring(s, a, b)
            if part.geom_type != 'LineString' or part.length <= 0: continue
            c = list(part.coords)
            na, nb = G.node(*c[0][:2]), G.node(*c[-1][:2])
            if not nl: nl.append((a, na))
            nl.append((b, nb))
            G.add_edge(na, nb, part)
        segnodes[i] = nl
    nodes = []
    for (i, d, pt, off) in snap:
        nl = segnodes[i]
        nodes.append(min(nl, key=lambda t: abs(t[0] - d))[1] if nl else G.node(pt.x, pt.y))
    return G, nodes, [x[3] for x in snap]


# ---------------------------------------------------------------- clustering
def components(P, gap):
    n = len(P); lab = [-1] * n; c = 0
    D = np.sqrt(((P[:, None, :] - P[None, :, :]) ** 2).sum(-1))
    for i in range(n):
        if lab[i] >= 0: continue
        stack = [i]; lab[i] = c
        while stack:
            u = stack.pop()
            for v in np.nonzero((D[u] <= gap) & (np.array(lab) < 0))[0]:
                lab[v] = c; stack.append(int(v))
        c += 1
    out = defaultdict(list)
    for i, l in enumerate(lab): out[l].append(i)
    return list(out.values())


def radius(P, idx):
    c = P[idx].mean(0)
    return float(np.sqrt(((P[idx] - c) ** 2).sum(1)).max())


def bisect(P, idx, cap, rad, depth=0):
    """تقسيم ثنائي متكرر؛ الأولوية لملء المجموعات حتى cap (أقل عدد سبلترات)."""
    n = len(idx)
    if n <= 1: return [idx]
    if n <= cap and radius(P, idx) <= rad: return [idx]
    if depth > 60: return [[i] for i in idx]
    X = P[idx] - P[idx].mean(0)
    w, v = np.linalg.eigh(np.cov(X.T) if n > 1 else np.eye(2))
    ax = v[:, -1]; order = [idx[j] for j in np.argsort(X @ ax)]
    if n > cap:
        k = math.ceil(n / cap); k1 = max(1, k // 2); cut = min(n - 1, cap * k1)
    else:
        cut = n // 2
    return bisect(P, order[:cut], cap, rad, depth + 1) + bisect(P, order[cut:], cap, rad, depth + 1)


def cluster(P, cap, rad, gap):
    out = []
    for comp in components(P, gap):
        out += bisect(P, comp, cap, rad)
    return out


def best_node(G, cand, members, unreach_pen=1e6, cutoff=700):
    best = None
    for c in set(cand):
        dist, _ = G.dijkstra(c, cutoff)
        cost = sum(dist.get(m, unreach_pen) for m in members)
        mx = max(dist.get(m, unreach_pen) for m in members)
        key = (cost, mx)
        if best is None or key < best[0]: best = (key, c)
    return best[1]


# ---------------------------------------------------------------- cables
def pick_cores(used, sizes, growth, strict):
    need = math.ceil(used * growth)
    for s in sizes:
        if (s > need) if strict else (s >= need): return s
    return sizes[-1]


def tree_cables(G, root, terminals, tag, sizes, growth, strict, closure_on_terminal_pass=False):
    """terminals: {node: weight}. يرجع (cables, closure_nodes, unreachable)."""
    dist, pred = G.dijkstra(root)
    unreach = [t for t in terminals if t != root and t not in dist]
    parent = {}; kids = defaultdict(set); peid = {}
    for t in terminals:
        if t == root or t not in dist: continue
        v = t
        while v != root:
            u, eid = pred[v]; parent[v] = u; peid[v] = eid; kids[u].add(v); v = u
    # عدد الطرفيات تحت كل عقدة
    order = sorted(parent, key=lambda n: -dist[n]); load = defaultdict(float)
    for t, w in terminals.items():
        if t in dist and t != root: load[t] += w
    for n in order: load[parent[n]] += load[n]
    cables = []; clos = []
    def is_break(n):
        return n in terminals or len(kids[n]) != 1
    for start in list(kids[root]) if root in kids else []:
        pass
    # قطع السلاسل: تبدأ كل سلسلة من أب (جذر أو عقدة قطع) وتنتهي عند أول عقدة قطع
    stack = [root]
    while stack:
        top = stack.pop()
        for ch in sorted(kids[top]):
            geoms = []; n = ch; prev = top
            while True:
                geom, a, b = G.edges[peid[n]]
                c = list(geom.coords)
                if (round(c[0][0], 1), round(c[0][1], 1)) != (round(G.xy[prev][0], 1), round(G.xy[prev][1], 1)): c = c[::-1]
                geoms.append(c)
                if is_break(n) or len(kids[n]) == 0: break
                prev = n; n = next(iter(kids[n]))
            coords = list(geoms[0])
            for c in geoms[1:]: coords += c[1:]
            used = int(round(load[n]))
            cables.append({'from': top, 'to': n, 'coords': coords, 'used': used,
                           'cores': pick_cores(used, sizes, growth, strict)})
            stack.append(n)
    for n in kids:
        if n == root: continue
        if len(kids[n]) >= 2 or (n in terminals and len(kids[n]) >= 1): clos.append(n)
    return cables, clos, unreach


# ---------------------------------------------------------------- gpkg writer
def _blob(g, srs):
    return b'GP' + bytes([0, 1]) + struct.pack('<i', srs) + _wkb.dumps(g, output_dimension=2)


WKT32637 = ('PROJCS["WGS 84 / UTM zone 37N",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
            'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",39],PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]')


def write_gpkg(path, layers, srs=32637):
    """layers: {name: (geomtype, [(fieldname, sqltype)], [(geom, [values])])}"""
    if os.path.exists(path): os.remove(path)
    con = sqlite3.connect(path)
    con.execute('PRAGMA application_id=1196444487'); con.execute('PRAGMA user_version=10300')
    con.executescript('''
    CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
      organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
      description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
    CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
      srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL, PRIMARY KEY (table_name, column_name));''')
    con.executemany('insert into gpkg_spatial_ref_sys values (?,?,?,?,?,?)', [
        ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', None),
        ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', None),
        ('WGS 84 / UTM zone 37N', 32637, 'EPSG', 32637, WKT32637, None)])
    for name, (gt, fields, rows) in layers.items():
        cols = ', '.join('"%s" %s' % (f, t) for f, t in fields)
        con.execute('CREATE TABLE "%s" (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB%s)' % (name, (', ' + cols) if cols else ''))
        ph = ','.join('?' * (1 + len(fields)))
        con.executemany('insert into "%s" (geom%s) values (%s)' % (name, ''.join(',"%s"' % f for f, _ in fields), ph),
                        [(_blob(g, srs), *vals) for g, vals in rows])
        bb = [g.bounds for g, _ in rows if g is not None]
        e = (min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)) if bb else (None,) * 4
        con.execute('insert into gpkg_contents (table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) values (?,?,?,?,?,?,?,?)',
                    (name, 'features', name, *e, srs))
        con.execute('insert into gpkg_geometry_columns values (?,?,?,?,0,0)', (name, 'geom', gt, srs))
    con.commit(); con.close()


# ---------------------------------------------------------------- main generator
def generate(inp, outdir, STD, log=print):
    t0 = time.time(); D = dget(STD); LAYn = STD['layers']
    data = U.read_gpkg(inp)
    B = data.get(LAYn['buildings'], []); R = data.get('مسارات_الطرق', []); C = data.get(LAYn['center'], [])
    import ftth_poles
    _pn = ftth_poles._find_layer_name(data)
    poles = data.get(_pn, []) if _pn else []
    if not B or not R or not C: raise SystemExit('input gpkg must contain buildings, roads (مسارات_الطرق) and center layers')
    if B[0]['geometry'].x < 1e5: raise SystemExit('geometry must be projected (UTM); got lon/lat')
    bp = [b['geometry'] for b in B]; olt = C[0]['geometry']
    G, nodes, offs = build_graph([r['geometry'] for r in R], bp + [olt])
    bnode = nodes[:-1]; rootn = nodes[-1]
    log('roads graph: %d nodes, %d edges' % (len(G.xy), len(G.edges)))
    dist0, _ = G.dijkstra(rootn)
    reach = [n in dist0 for n in bnode]
    log('buildings: %d | unreachable from OLT: %d | max snap offset %.0f m' % (len(B), reach.count(False), max(offs)))
    issues = []
    far = D.get('max_drop_m', 80.0)
    for i, o in enumerate(offs[:-1]):
        if o > far: issues.append(('تنبيه', B[i]['Building_ID'], 'بعيد %d م عن أقرب طريق (> %d): تأكد من طريق مفقود' % (o, far)))
    # --- ثانوي
    sec = D['secondary']
    P = np.array([[p.x, p.y] for p in bp])
    keep = [i for i, r in enumerate(reach) if r]
    for i, r in enumerate(reach):
        if not r: issues.append(('تنبيه', B[i]['Building_ID'], 'مبنى على جزء طرق غير موصول بالمركز: استبعد من التصميم'))
    cl = cluster(P[keep], sec['max_buildings'], sec['max_radius_m'], sec['component_gap_m'])
    cl = [[keep[j] for j in c] for c in cl]
    snap_pole = D['snap_pole_m']
    PP = [p['geometry'] for p in poles if p.get('geometry') is not None]
    ptree = STRtree(PP) if PP else None
    def to_pole(node):
        if not ptree: return None
        pt = Point(*G.xy[node]); j = int(ptree.nearest(pt))
        return PP[j] if PP[j].distance(pt) <= snap_pole else None
    sec_nodes = []
    for c in cl:
        sec_nodes.append(best_node(G, [bnode[i] for i in c], [bnode[i] for i in c], cutoff=sec['max_radius_m'] * 4))
    log('secondary clusters: %d (%.1fs)' % (len(cl), time.time() - t0))
    # --- رئيسي
    pr = D['primary']
    SP = np.array([G.xy[n] for n in sec_nodes])
    gl = cluster(SP, pr['max_secondaries'], pr['max_radius_m'], pr['component_gap_m'])
    prim_nodes = []
    for g in gl:
        mem = [sec_nodes[j] for j in g]
        prim_nodes.append(best_node(G, mem, mem, cutoff=pr['max_radius_m'] * 4))
    # ترتيب الرئيسيات بالبعد عن المركز
    order = sorted(range(len(gl)), key=lambda k: dist0.get(prim_nodes[k], 1e9))
    gl = [gl[k] for k in order]; prim_nodes = [prim_nodes[k] for k in order]
    log('primary groups: %d (%.1fs)' % (len(gl), time.time() - t0))
    # أرقام
    sec_id = {}; sec_prim = {}
    n_s = 0
    for pi, g in enumerate(gl):
        for j in sorted(g, key=lambda j: dist0.get(sec_nodes[j], 1e9)):
            n_s += 1; sec_id[j] = 'S%03d' % n_s; sec_prim[j] = pi
    col = lambda pi: PALETTE[pi % len(PALETTE)]
    b_sec = {}
    for j, c in enumerate(cl):
        for i in c: b_sec[i] = j
    # --- كبلات فرعية
    cs = D['cable_sizing']; closures = []
    sub_rows = []; sec_dist = {}; prim_stats = {}
    for pi, g in enumerate(gl):
        root = prim_nodes[pi]; term = defaultdict(float)
        for j in g: term[sec_nodes[j]] += 1
        cab, clo, un = tree_cables(G, root, term, 'B', cs['branch_sizes'], cs['growth'], False)
        dist, _ = G.dijkstra(root)
        for j in g: sec_dist[j] = dist.get(sec_nodes[j], 0.0)
        for u in un: issues.append(('تنبيه', 'P%02d' % (pi + 1), 'سبلتر فرعي غير موصول بالرئيسي'))
        for k, c in enumerate(cab, 1):
            ls = LineString(c['coords']); L = ls.length
            sub_rows.append((ls, ['B-P%02d-%d' % (pi + 1, k), 'P%02d' % (pi + 1), c['cores'], c['used'],
                                  round((c['cores'] - c['used']) / c['cores'] * 100, 1), round(L, 1),
                                  math.ceil(L * STD['cable_order_factor']), '', '']))
        for n in clo:
            if n != root: closures.append(('تفرع فرعي', n))
        prim_stats[pi] = (max([sec_dist[j] for j in g] or [0]), dist0.get(root, 0.0))
    # --- كبلات رئيسية
    term = defaultdict(float)
    for pi, n in enumerate(prim_nodes): term[n] += 1
    cab, clo, un = tree_cables(G, rootn, term, 'M', cs['main_sizes'], cs['growth'], cs['main_strict'])
    for u in un: issues.append(('خطأ', 'سبلتر رئيسي', 'غير موصول بالمركز'))
    main_rows = []; olt_c = list(olt.coords)[0][:2]
    for k, c in enumerate(cab, 1):
        co = c['coords']
        if c['from'] == rootn and math.hypot(co[0][0] - olt_c[0], co[0][1] - olt_c[1]) > 0.5: co = [olt_c] + list(co)
        ls = LineString(co); L = ls.length
        main_rows.append((ls, ['M-%03d' % k, c['cores'], c['used'], int(math.ceil(c['used'] * cs['growth'])),
                               round((c['cores'] - c['used']) / c['cores'] * 100, 1), round(L, 1),
                               math.ceil(L * STD['cable_order_factor'])]))
    for n in clo: closures.append(('تفرع رئيسي', n))
    # --- طبقات الإخراج
    def pt_of(node):
        p = to_pole(node); return p if p is not None else Point(*G.xy[node])
    sec_rows = []
    for j in sorted(sec_id, key=lambda j: sec_id[j]):
        nb = len(cl[j]); pi = sec_prim[j]
        sec_rows.append((pt_of(sec_nodes[j]), [sec_id[j], 'P%02d' % (pi + 1), col(pi), nb,
                                              STD['splitter']['ports'] - nb, round(sec_dist[j]), '']))
    prim_rows = []
    for pi, g in enumerate(gl):
        prim_rows.append((pt_of(prim_nodes[pi]), ['P%02d' % (pi + 1), 'P%02d' % (pi + 1), col(pi), len(g),
                                                 STD['splitter']['ports'] - len(g), round(prim_stats[pi][0]), round(prim_stats[pi][1])]))
    bld_rows = []
    for i, b in enumerate(B):
        if i in b_sec:
            j = b_sec[i]; bld_rows.append((b['geometry'], [b['Building_ID'], sec_id[j], 'P%02d' % (sec_prim[j] + 1)]))
        else:
            bld_rows.append((b['geometry'], [b['Building_ID'], '', '']))
    cid = 0; clos_rows = {'تفرع رئيسي': [], 'تفرع فرعي': []}
    for ty in ('تفرع رئيسي', 'تفرع فرعي'):
        for t, n in closures:
            if t == ty:
                cid += 1; clos_rows[ty].append((Point(*G.xy[n]), ['CL%03d' % cid, ty]))
    T = lambda f: [(a, 'TEXT') if t == 'T' else (a, 'REAL') if t == 'R' else (a, 'INTEGER') for a, t in f]
    layers = {
        LAYn['primary_splitters']: ('POINT', T([('Primary_ID', 'T'), ('Group_ID', 'T'), ('Group_Colour', 'T'), ('Secondaries', 'I'),
                                                 ('Spare_Ports', 'I'), ('Max_Dist_m', 'I'), ('Main_Path_m', 'I')]), prim_rows),
        LAYn['secondary_splitters']: ('POINT', T([('Secondary_ID', 'T'), ('Group_ID', 'T'), ('Group_Colour', 'T'), ('Buildings', 'I'),
                                                   ('Spare_Ports', 'I'), ('Dist_from_Primary_m', 'I'), ('Note', 'T')]), sec_rows),
        LAYn['main_cables']: ('LINESTRING', T([('Cable_ID', 'T'), ('Cores', 'I'), ('Used', 'I'), ('Used_10y', 'I'), ('Spare_pct', 'R'),
                                               ('Length_m', 'R'), ('Order_m', 'I')]), main_rows),
        LAYn['branch_cables']: ('LINESTRING', T([('Cable_ID', 'T'), ('Group_ID', 'T'), ('Cores', 'I'), ('Used', 'I'), ('Spare_pct', 'R'),
                                                 ('Length_m', 'R'), ('Order_m', 'I'), ('Parallel', 'T'), ('Raised_10y', 'T')]), sub_rows),
        LAYn['buildings']: ('POINT', T([('Building_ID', 'T'), ('Secondary_ID', 'T'), ('Group_ID', 'T')]), bld_rows),
        LAYn['center']: ('POINT', T([('Name', 'T')]), [(olt, [C[0].get('Name', 'المركز')])]),
        LAYn['closure_main']: ('POINT', T([('Closure_ID', 'T'), ('Type', 'T')]), clos_rows['تفرع رئيسي']),
        LAYn['closure_branch']: ('POINT', T([('Closure_ID', 'T'), ('Type', 'T')]), clos_rows['تفرع فرعي']),
        LAYn['closure_merge']: ('POINT', T([('Closure_ID', 'T'), ('Type', 'T')]), []),
        'مسارات_الطرق': ('MULTILINESTRING', T([('Name', 'T')]), [(r['geometry'] if r['geometry'].geom_type == 'MultiLineString'
                                                                    else MultiLineString([r['geometry']]), [r.get('Name', 'طريق')]) for r in R]),
    }
    # --- طبقة الأعمدة: من المسح إن وُجدت، وإلا مقترحة بالقاعدة التقديرية (تُستبدل بالمسح لاحقاً)
    import ftth_poles
    TY = {'existing': 'موجود', 'new': 'جديد', 'unknown': ''}; RO = {'stay': 'شدّادة', 'mid': 'وسطي', 'branch': 'تفرع', 'unknown': ''}
    pname = ftth_poles._find_layer_name(data)
    if pname and data.get(pname):
        srs_in = ftth_poles._gpkg_srs(inp, pname)
        norm = ftth_poles.normalise([dict(r, geometry=ftth_poles._to_study_crs(r['geometry'], srs_in)) for r in data[pname]])
        pole_rows = [(n['geometry'], [n['id'], TY[n['type']], RO[n['role']], float(n['height']) if isinstance(n['height'], (int, float)) else None, 'مسح'])
                     for n in norm if n['geometry'] is not None]
        poles_src = 'مسح ميداني'
    else:
        special = [(olt.x, olt.y)] + [(g.x, g.y) for g, _ in prim_rows + sec_rows] + [(g.x, g.y) for rows in clos_rows.values() for g, _ in rows]
        sug = ftth_poles.suggest([r[0] for r in main_rows + sub_rows], special)
        pole_rows = [(Point(x, y), ['PL%04d' % i, 'جديد', RO[k], None, 'مقترح']) for i, (x, y, k) in enumerate(sug, 1)]
        poles_src = 'مقترحة بالقاعدة التقديرية'
    layers[LAYn['poles']] = ('POINT', T([('Pole_ID', 'T'), ('Type', 'T'), ('Role', 'T'), ('Height', 'R'), ('Source', 'T')]), pole_rows)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, 'FTTH_draft.gpkg')
    # الطبقات ذات صفر عناصر لا تُكتب (حدود gpkg بلا مغلف)
    layers = {k: v for k, v in layers.items() if v[2]}
    write_gpkg(out, layers)
    stats = {'buildings': len(B), 'buildings_served': len(keep), 'secondaries': len(sec_rows), 'primaries': len(prim_rows),
             'sub_cables': len(sub_rows), 'main_cables': len(main_rows),
             'sub_m': round(sum(r[1][5] for r in sub_rows)), 'main_m': round(sum(r[1][5] for r in main_rows)),
             'closures_main': len(clos_rows['تفرع رئيسي']), 'closures_branch': len(clos_rows['تفرع فرعي']),
             'poles': len(pole_rows), 'poles_source': poles_src, 'issues': len(issues), 'seconds': round(time.time() - t0, 1)}
    # جلسة أمان
    if stats['seconds'] > D['max_seconds']: issues.append(('تنبيه', 'عام', 'تجاوز زمن التنفيذ الحد %ds' % D['max_seconds']))
    with open(os.path.join(outdir, 'تقرير_المولد.txt'), 'w', encoding='utf-8') as f:
        f.write('مسودة تصميم آلي — تحتاج مراجعة بشرية في QGIS قبل الاعتماد\n')
        for k, v in stats.items(): f.write('%s: %s\n' % (k, v))
        f.write('\nملاحظات (%d):\n' % len(issues))
        for s, w, m in issues: f.write('- [%s] %s: %s\n' % (s, w, m))
    with open(os.path.join(outdir, 'stats.json'), 'w', encoding='utf-8') as f: json.dump(stats, f, ensure_ascii=False, indent=1)
    return out, stats, issues


def make_qgz(template_qgz, old_gpkg_name, new_gpkg, outdir):
    """نسخة من مشروع QGIS مرجعي مع استبدال اسم الـgpkg (نفس أسماء الطبقات)."""
    with zipfile.ZipFile(template_qgz) as z:
        nm = [n for n in z.namelist() if n.endswith('.qgs')][0]; xml = z.read(nm).decode('utf-8')
    xml = xml.replace(old_gpkg_name, os.path.basename(new_gpkg))
    q = os.path.join(outdir, 'FTTH_draft.qgz')
    with zipfile.ZipFile(q, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('FTTH_draft.qgs', xml)
    return q


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='gpkg فيه المباني ومسارات_الطرق والمركز (وطبقة الأعمدة اختيارياً)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--study', help='مجلد دراسة (study.json) لأخذ المعايير منه')
    ap.add_argument('--qgz-template', help='(غير مستعمل: المشروع يُبنى من القالب الداخلي)')
    a = ap.parse_args(argv)
    cfg = {}
    if a.study:
        cfg = json.load(open(os.path.join(a.study, 'study.json'), encoding='utf-8'))
    ftth_std.load(cfg, os.path.dirname(HERE))
    out, stats, issues = generate(a.input, a.out, ftth_std.STD)
    import ftth_qgis
    town = cfg.get('town_ar') or 'البلدة'
    ftth_qgis.build(out, a.out, town, 'FTTH %s (مسودة)' % town)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
