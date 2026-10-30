# -*- coding: utf-8 -*-
"""بناء مشروع QGIS (.qgz) من أي gpkg بنفس أسماء الطبقات، انطلاقاً من قالب منسَّق مسبقاً.

التنسيق (أحجام الخطوط، ألوان المجموعات، التسميات، الوحدات بالأمتار، حدود المقياس، خلفيات Google،
تخطيطات الطباعة) محفوظ في templates/qgis_template.qgs وهو مشروع أورم نفسه. لتغيير التنسيق: افتح القالب
في QGIS، عدّله، احفظه مكانه. ما يفعله هذا الملف:
  - يستبدل اسم الـgpkg والبلدة والعنوان،
  - يحذف طبقات القالب غير الموجودة في الـgpkg (مثلاً المباني أو الحفر) مع مراجعها،
  - يضيف طبقة الأعمدة إن وُجدت (بنمط نقطي منسوخ من غرف التفتيش)،
  - يضبط امتداد الخريطة من الـgpkg، ويجعل خلفية Google Satellite وحدها ظاهرة (أو ما تحدده qgis.basemap).
"""
import os, re, sys, uuid, zipfile, sqlite3, json, copy
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'templates', 'qgis_template.qgs')
TEMPLATE_GPKG = 'FTTH_Orem.gpkg'
TEMPLATE_TOWN = 'أورم الجوز'
BASEMAPS = ['Google Satellite', 'Google Terrain', 'Google Hybrid']


def gpkg_info(path):
    con = sqlite3.connect(path)
    names = {r[0] for r in con.execute("select table_name from gpkg_contents where data_type='features'")}
    ext = None
    for r in con.execute("select min_x,min_y,max_x,max_y from gpkg_contents where data_type='features' and min_x is not null"):
        ext = r if ext is None else (min(ext[0], r[0]), min(ext[1], r[1]), max(ext[2], r[2]), max(ext[3], r[3]))
    con.close(); return names, ext


def _refs(el, ids):
    for e in el.iter():
        if e.text and e.text.strip() in ids: return True
        if any(v in ids for v in e.attrib.values()): return True
    return False


def build(gpkg, outdir, town, title=None, basemap='Google Satellite', poles_layer='الأعمدة', template=None, log=print):
    names, ext = gpkg_info(gpkg)
    tree = ET.parse(template or TEMPLATE); root = tree.getroot()
    pl = root.find('projectlayers')
    gname = os.path.basename(gpkg)
    # 1) حذف الطبقات غير الموجودة
    gone = []
    for m in list(pl):
        if m.get('type') != 'vector': continue
        ds = m.findtext('datasource') or ''
        mm = re.search(r'layername=(.*)$', ds)
        if mm and mm.group(1) not in names: gone.append(m)
    gone_ids = {m.findtext('id') for m in gone}
    src_poles = [copy.deepcopy(m) for m in pl if (m.findtext('datasource') or '').endswith('layername=غرف_التفتيش')]
    src_tree = [copy.deepcopy(t) for t in root.iter('layer-tree-layer') if t.get('name') == 'غرف التفتيش']
    gone_names = [m.findtext('layername') for m in gone]
    KILL = {'layer-tree-layer', 'maplayer', 'layer', 'item', 'legendlayer', 'legendlayerfile'}
    def prune(parent):
        for c in list(parent):
            if c.tag in KILL and _refs(c, gone_ids): parent.remove(c)
            else: prune(c)
    prune(root)
    # 2) طبقة الأعمدة (إن وُجدت ولم تكن في القالب)
    added = []
    if poles_layer in names:
        if src_poles and src_tree and not any((m.findtext('datasource') or '').endswith('layername=' + poles_layer) for m in pl):
            nm = src_poles[0]; nid = 'poles_' + uuid.uuid4().hex
            nm.find('id').text = nid
            nm.find('layername').text = 'الأعمدة (مسح ميداني)'
            nm.find('datasource').text = './%s|layername=%s' % (gname, poles_layer)
            pl.append(nm)
            nt = src_tree[0]; nt.set('id', nid); nt.set('name', 'الأعمدة (مسح ميداني)'); nt.set('source', nm.find('datasource').text)
            grp = root.find('layer-tree-group'); kids = list(grp)
            bi = [i for i, k in enumerate(kids) if k.get('name', '').startswith('المباني')]
            pos = bi[0] if bi else max(i for i, k in enumerate(kids) if k.tag == 'layer-tree-layer' and k.get('providerKey') == 'ogr') + 1
            grp.insert(pos, nt)
            e = ET.SubElement(root.find('layerorder'), 'layer'); e.set('id', nid)
            added.append(poles_layer)
    # 3) خلفية واحدة ظاهرة
    for t in root.iter('layer-tree-layer'):
        if t.get('name') in BASEMAPS: t.set('checked', 'Qt::Checked' if t.get('name') == basemap else 'Qt::Unchecked')
    # 4) الامتداد
    if ext:
        mx, my = (ext[2] - ext[0]) * 0.05 + 50, (ext[3] - ext[1]) * 0.05 + 50
        ce = root.find('mapcanvas').find('extent')
        for k, v in (('xmin', ext[0] - mx), ('ymin', ext[1] - my), ('xmax', ext[2] + mx), ('ymax', ext[3] + my)): ce.find(k).text = repr(v)
    xml = ET.tostring(root, encoding='unicode')
    xml = xml.replace('./' + TEMPLATE_GPKG, './' + gname).replace(TEMPLATE_TOWN, town)
    if title: xml = re.sub(r'<title>.*?</title>', '<title>%s</title>' % title, xml, count=1)
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(gname)[0]
    q = os.path.join(outdir, stem + '_auto.qgz')   # لا يكتب فوق مشروعك المعدَّل يدوياً
    stem = stem + '_auto'
    with zipfile.ZipFile(q, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(stem + '.qgs', '<?xml version="1.0" encoding="UTF-8"?>\n' + xml)
    log('QGIS project: %s | removed layers: %s | added: %s' % (q, '، '.join(gone_names) or '-', '، '.join(added) or '-'))
    return q, gone_names, added


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--gpkg', required=True); ap.add_argument('--out')
    ap.add_argument('--town', required=True); ap.add_argument('--basemap', default='Google Satellite')
    a = ap.parse_args()
    build(a.gpkg, a.out or os.path.dirname(os.path.abspath(a.gpkg)), a.town, 'FTTH ' + a.town, a.basemap)
