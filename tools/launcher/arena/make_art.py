#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes Assets/Art.xaml (WPF drawings of the SSBU Arena art: the hitbox scene of the site, the brand mark, the
wordmark, a gear) and Assets/arena.ico (the brand mark on its tile) from Assets/arena-art.svg and the site's paths.
WPF has no SVG: the few element kinds the art uses (g, rect, circle, ellipse, path, linear / radial gradients, translate /
rotate / scale) become DrawingGroups and GeometryDrawings.
    python tools/launcher/arena/make_art.py"""
import math
import os
import re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'Assets')
NS = '{http://www.w3.org/2000/svg}'

MARK = ['M22 3h11L11 45H0L22 3Zm13 6 19 36H42L29 20l6-11Z', 'M22 31h10l5 9H17l5-9Z']           # viewBox 0 0 56 48
WORDMARK = ['M0 30 11 2h9l11 28h-9l-2-6H10l-2 6H0Zm13-13h5l-2.5-8-2.5 8ZM36 2h18c8 0 12 4 12 10 0 5-3 8-7 9l9 9H57l-8-9h-4v9h-9V2Zm9 7v6h8c3 0 4-1 4-3s-1-3-4-3h-8Z',
            'M74 2h26v7H83v4h15v7H83v4h17v6H74V2Zm33 28V2h9l12 16V2h9v28h-9l-12-16v16h-9Z',
            'm144 30 11-28h9l11 28h-9l-2-6h-10l-2 6h-8Zm13-13h5l-2.5-8-2.5 8Z']                  # viewBox 0 0 181 32
EVENODD_WORDMARK = (True, False, True)


def num(s, d=0.0):
    return float(s) if s not in (None, '') else d


def color(c, op=1.0):
    """#rgb / #rrggbb + opacity -> #aarrggbb"""
    c = c.strip().lstrip('#')
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    a = max(0, min(255, round(op * 255)))
    return '#%02X%s' % (a, c.upper())


def transforms(t):
    """SVG transform list -> WPF transforms in the order WPF applies them (SVG's last one first)"""
    out = []
    for name, args in re.findall(r'(\w+)\(([^)]*)\)', t or ''):
        a = [float(x) for x in re.split(r'[\s,]+', args.strip()) if x]
        if name == 'translate':
            out.append('<TranslateTransform X="%g" Y="%g"/>' % (a[0], a[1] if len(a) > 1 else 0))
        elif name == 'rotate':
            out.append('<RotateTransform Angle="%g"%s/>' % (a[0], ' CenterX="%g" CenterY="%g"' % (a[1], a[2]) if len(a) == 3 else ''))
        elif name == 'scale':
            out.append('<ScaleTransform ScaleX="%g" ScaleY="%g"/>' % (a[0], a[1] if len(a) > 1 else a[0]))
        else:
            raise ValueError(name)
    out.reverse()
    if not out:
        return ''
    if len(out) == 1:
        return out[0]
    return '<TransformGroup>' + ''.join(out) + '</TransformGroup>'


class Conv:
    def __init__(self, root):
        self.grads = {}
        for g in root.iter():
            tag = g.tag.replace(NS, '')
            if tag in ('linearGradient', 'radialGradient'):
                self.grads[g.get('id')] = g

    def brush(self, paint, op):
        if paint in (None, 'none'):
            return None
        m = re.match(r'url\(#(.+)\)', paint)
        if not m:
            return '<SolidColorBrush Color="%s"/>' % color(paint, op)
        g = self.grads[m.group(1)]
        stops = ''.join('<GradientStop Color="%s" Offset="%g"/>' % (color(s.get('stop-color'), num(s.get('stop-opacity'), 1) * op), num(s.get('offset'), 0))
                        for s in g if s.tag.replace(NS, '') == 'stop')
        if g.tag.endswith('linearGradient'):
            if g.get('gradientUnits') == 'userSpaceOnUse':
                return ('<LinearGradientBrush MappingMode="Absolute" StartPoint="%g,%g" EndPoint="%g,%g">%s</LinearGradientBrush>'
                        % (num(g.get('x1')), num(g.get('y1')), num(g.get('x2')), num(g.get('y2')), stops))
            return '<LinearGradientBrush StartPoint="0,0" EndPoint="1,0">%s</LinearGradientBrush>' % stops
        return '<RadialGradientBrush>%s</RadialGradientBrush>' % stops

    def geometry(self, el, tag):
        if tag == 'rect':
            x, y, w, h = (num(el.get(k)) for k in ('x', 'y', 'width', 'height'))
            rx = num(el.get('rx'), num(el.get('ry')))
            return '<RectangleGeometry Rect="%g,%g,%g,%g" RadiusX="%g" RadiusY="%g"/>' % (x, y, w, h, rx, num(el.get('ry'), rx))
        if tag == 'circle':
            r = num(el.get('r'))
            return '<EllipseGeometry Center="%g,%g" RadiusX="%g" RadiusY="%g"/>' % (num(el.get('cx')), num(el.get('cy')), r, r)
        if tag == 'ellipse':
            return '<EllipseGeometry Center="%g,%g" RadiusX="%g" RadiusY="%g"/>' % (num(el.get('cx')), num(el.get('cy')), num(el.get('rx')), num(el.get('ry')))
        if tag == 'path':
            rule = 'EvenOdd' if el.get('fill-rule') == 'evenodd' else 'Nonzero'
            return '<PathGeometry FillRule="%s" Figures="%s"/>' % (rule, el.get('d'))
        return None

    def element(self, el, st, out, ind):
        tag = el.tag.replace(NS, '')
        if tag in ('defs', 'linearGradient', 'radialGradient', 'stop'):
            return
        st = dict(st)
        for k in ('fill', 'stroke', 'stroke-width', 'stroke-linecap', 'fill-opacity', 'stroke-opacity', 'color'):
            if el.get(k) is not None:
                st[k] = el.get(k)
        op = num(el.get('opacity'), 1)
        tr = transforms(el.get('transform'))
        if tag in ('g', 'svg'):
            out.append(ind + '<DrawingGroup%s>' % (' Opacity="%g"' % op if op != 1 else ''))
            if tr:
                out.append(ind + '  <DrawingGroup.Transform>' + tr + '</DrawingGroup.Transform>')
            for c in el:
                self.element(c, st, out, ind + '  ')
            out.append(ind + '</DrawingGroup>')
            return
        geo = self.geometry(el, tag)
        if geo is None:
            raise ValueError(tag)
        cur = st.get('color', '#000')
        fill = st.get('fill', '#000')
        fill = cur if fill == 'currentColor' else fill
        stroke = st.get('stroke')
        stroke = cur if stroke == 'currentColor' else stroke
        fb = self.brush(fill, num(st.get('fill-opacity'), 1))
        sb = self.brush(stroke, num(st.get('stroke-opacity'), 1))
        if not fb and not sb:
            return
        wrap = tr or op != 1
        if wrap:
            out.append(ind + '<DrawingGroup%s>' % (' Opacity="%g"' % op if op != 1 else ''))
            if tr:
                out.append(ind + '  <DrawingGroup.Transform>' + tr + '</DrawingGroup.Transform>')
        i2 = ind + ('  ' if wrap else '')
        s = i2 + '<GeometryDrawing>'
        if fb:
            s += '<GeometryDrawing.Brush>' + fb + '</GeometryDrawing.Brush>'
        if sb:
            cap = {'round': 'Round', 'square': 'Square'}.get(st.get('stroke-linecap'), 'Flat')
            s += ('<GeometryDrawing.Pen><Pen Thickness="%g" StartLineCap="%s" EndLineCap="%s">'
                  '<Pen.Brush>%s</Pen.Brush></Pen></GeometryDrawing.Pen>') % (num(st.get('stroke-width'), 1), cap, cap, sb)
        s += '<GeometryDrawing.Geometry>' + geo + '</GeometryDrawing.Geometry></GeometryDrawing>'
        out.append(s)
        if wrap:
            out.append(ind + '</DrawingGroup>')


def scene():
    root = ET.parse(os.path.join(ASSETS, 'arena-art.svg')).getroot()
    vb = [float(x) for x in root.get('viewBox').split()]
    c = Conv(root)
    out = ['  <DrawingImage x:Key="ArenaArt"><DrawingImage.Drawing>',
           '    <DrawingGroup ClipGeometry="M%g,%g h%g v%g h%g Z">' % (vb[0], vb[1], vb[2], vb[3], -vb[2]),
           '      <GeometryDrawing Brush="Transparent"><GeometryDrawing.Geometry><RectangleGeometry Rect="%g,%g,%g,%g"/></GeometryDrawing.Geometry></GeometryDrawing>' % tuple(vb)]
    st = {'fill': root.get('fill', '#000')}
    for ch in root:
        c.element(ch, st, out, '      ')
    out += ['    </DrawingGroup>', '  </DrawingImage.Drawing></DrawingImage>']
    return out


def gear(teeth=8, ro=11.0, ri=8.6, hole=3.6):
    """a gear outline centred on (12,12): teeth with flat tops, a round hole (even-odd)"""
    pts = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth
        w = math.pi / teeth
        for a, r in ((a0 - w * 0.62, ri), (a0 - w * 0.36, ro), (a0 + w * 0.36, ro), (a0 + w * 0.62, ri)):
            pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    d = 'F0 M' + ' L'.join('%.2f,%.2f' % p for p in pts) + ' Z '
    d += 'M%.2f,12 A%.2f,%.2f 0 1 0 %.2f,12 A%.2f,%.2f 0 1 0 %.2f,12 Z' % (12 + hole, hole, hole, 12 - hole, hole, hole, 12 + hole)
    return d


def write_xaml():
    out = ['<!-- written by make_art.py: do not edit -->',
           '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"',
           '                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">']
    out += scene()
    out.append('  <Geometry x:Key="BrandMarkGeometry">F1 %s %s</Geometry>' % tuple(MARK))
    out.append('  <GeometryGroup x:Key="WordmarkGeometry" FillRule="EvenOdd">' +
               ''.join('<PathGeometry FillRule="%s" Figures="%s"/>' % ('EvenOdd' if eo else 'Nonzero', d) for d, eo in zip(WORDMARK, EVENODD_WORDMARK)) +
               '</GeometryGroup>')
    out.append('  <Geometry x:Key="GearGeometry">%s</Geometry>' % gear())
    out.append('</ResourceDictionary>')
    with open(os.path.join(ASSETS, 'Art.xaml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out) + '\n')


def write_ico():
    """the site's icon: the brand mark (#65c7ff) on a rounded #0c1119 tile, drawn 4x and scaled down"""
    from PIL import Image, ImageDraw

    def poly(d):
        """absolute points of a path made only of M/L/H/V/Z (upper and lower case), one list per subpath"""
        toks = re.findall(r'[MLHVZmlhvz]|-?[\d.]+', d)
        subs, cur, x, y, cmd, i = [], [], 0.0, 0.0, 'M', 0
        start = (0.0, 0.0)
        while i < len(toks):
            t = toks[i]
            if t.isalpha():
                cmd = t
                i += 1
                if cmd in 'Zz':
                    subs.append(cur); cur = []; x, y = start
                    cmd = 'l' if cmd == 'z' else 'L'
                continue
            if cmd in 'Mm':
                nx, ny = float(toks[i]), float(toks[i + 1]); i += 2
                if cmd == 'm':
                    nx, ny = nx + x, ny + y
                if cur:
                    subs.append(cur)
                cur = [(nx, ny)]; x, y = nx, ny; start = (x, y)
                cmd = 'l' if cmd == 'm' else 'L'
            elif cmd in 'Ll':
                nx, ny = float(toks[i]), float(toks[i + 1]); i += 2
                if cmd == 'l':
                    nx, ny = nx + x, ny + y
                x, y = nx, ny; cur.append((x, y))
            elif cmd in 'Hh':
                v = float(toks[i]); i += 1
                x = v + (x if cmd == 'h' else 0); cur.append((x, y))
            elif cmd in 'Vv':
                v = float(toks[i]); i += 1
                y = v + (y if cmd == 'v' else 0); cur.append((x, y))
        if cur:
            subs.append(cur)
        return subs

    S = 1024
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    k = S / 64
    dr.rounded_rectangle((0, 0, S - 1, S - 1), radius=14 * k, fill=(12, 17, 25, 255))
    for d in MARK:
        for sub in poly(d):
            dr.polygon([((9 + 0.82 * px) * k, (12 + 0.82 * py) * k) for px, py in sub], fill=(101, 199, 255, 255))
    img.save(os.path.join(ASSETS, 'arena.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == '__main__':
    write_xaml()
    write_ico()
    print('Assets/Art.xaml, Assets/arena.ico')
