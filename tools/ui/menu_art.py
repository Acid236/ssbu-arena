"""Authored Arena art for native BNTX slots; no screenshots or game art.

Uses the launcher's OFL Barlow fonts and the original Arena brand paths.
All labels fit their own card and remain independent of the native focus ring.
"""
import ast
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

import menu_design

ARENA = Path(__file__).resolve().parents[1] / 'launcher' / 'arena'
FONTS = ARENA / 'Assets' / 'Fonts'
CYAN = '#65c7ff'
WHITE = '#edf3f8'
SCALE = 2


class ArtDraw:
    """Draw in layout units while keeping text and vectors at double resolution."""
    def __init__(self, image, scale=SCALE):
        self.d, self.scale = ImageDraw.Draw(image), scale

    def coords(self, value):
        return tuple(self.coords(x) for x in value) if isinstance(value, (tuple,list)) else value*self.scale

    def __getattr__(self, name):
        def draw(coords, *args, **kwargs):
            for key in ('width', 'radius', 'stroke_width'):
                if key in kwargs:
                    kwargs[key] = round(kwargs[key]*self.scale)
            if 'font' in kwargs:
                f = kwargs['font']
                kwargs['font'] = f.font_variant(size=round(f.size*self.scale))
            return getattr(self.d, name)(self.coords(coords), *args, **kwargs)
        return draw

    def textlength(self, text, font):
        return self.d.textlength(text, font=font.font_variant(size=font.size*self.scale))/self.scale


def font(size, face='Barlow-Regular.ttf'):
    return ImageFont.truetype(str(FONTS / face), size)


def svg_paths(path):
    """Flatten the brand's M/L/H/V/C/S/Z paths; retain holes using even-odd fill."""
    tokens = re.findall(r'[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+)(?:e[-+]?\d+)?', path)
    i, x, y, start, points, result, previous = 0, 0., 0., (0., 0.), [], [], None
    command = None
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        op = command.upper()
        relative = command.islower()
        if op == 'Z':
            if points:
                result.append(points)
            points, (x, y), previous = [], start, None
            command = None
            continue
        n = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4}[op]
        values = list(map(float, tokens[i:i+n]))
        i += n
        def pt(a, b):
            return (a + x, b + y) if relative else (a, b)
        if op in ('M', 'L'):
            target = pt(*values)
            if op == 'M':
                if points:
                    result.append(points)
                points, start = [], target
                command = 'l' if relative else 'L'
            points.append(target)
            previous = None
        elif op in ('H', 'V'):
            target = ((values[0] + x if relative else values[0]), y) if op == 'H' else (x, (values[0] + y if relative else values[0]))
            points.append(target)
            previous = None
        else:
            if op == 'C':
                c1, c2, target = pt(*values[:2]), pt(*values[2:4]), pt(*values[4:])
            else:
                c1 = (2*x-previous[0], 2*y-previous[1]) if previous else (x, y)
                c2, target = pt(*values[:2]), pt(*values[2:])
            for j in range(1, 17):
                t = j / 16
                points.append(tuple((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d
                                    for a,b,c,d in zip((x,y),c1,c2,target)))
            previous = c2
        x, y = target
    if points:
        result.append(points)
    return result


def brand(size=(1040, 256)):
    """The same split-A and custom wordmark as the website and launcher."""
    constants = {}
    for item in ast.parse((ARENA / 'make_art.py').read_text(encoding='utf-8')).body:
        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('MARK', 'WORDMARK') for t in item.targets):
            constants[item.targets[0].id] = ast.literal_eval(item.value)
    im = Image.new('RGBA', (1032, 256))
    def paths(entries, transform, colour):
        for entry in entries:
            mask = Image.new('1', im.size)
            for polygon in svg_paths(entry):
                sub = Image.new('1', im.size)
                ImageDraw.Draw(sub).polygon([transform(x,y) for x,y in polygon], fill=1)
                mask = ImageChops.logical_xor(mask, sub)
            im.paste(colour, (0,0), mask.convert('L'))
    paths(constants['MARK'], lambda x,y: (x*4, (y+8)*4), CYAN)
    paths(constants['WORDMARK'], lambda x,y: ((77+x-.14054*y)*4, (24+y)*4), WHITE)
    ImageDraw.Draw(im).text((308, 6), 'S S B U', font=font(39, 'Barlow-Bold.ttf'), fill=WHITE)
    return im.resize(size, Image.Resampling.LANCZOS)


def card_art(name):
    from menu_textures import icon
    card = menu_design.CARDS[name]
    geo = menu_design.texture_geometry(name)
    w, h = geo['w'], geo['h']
    yy, xx = np.mgrid[:h, :w]
    glow = np.exp(-((xx-w*.76)**2/(w*.46)**2 + (yy-h*.24)**2/(h*.9)**2))
    colours = np.stack([16+8*glow, 25+17*glow, 38+25*glow, np.full_like(glow, 255)], axis=-1)
    im = Image.fromarray(colours.astype('uint8'), 'RGBA').resize((w*SCALE,h*SCALE), Image.Resampling.BICUBIC)
    d = ArtDraw(im)
    # Restrained technical illustration on the right, clear of the labels.
    cx, cy, r = w-160, h*.52, 138
    for rr in (r, r-18, r-45):
        d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr), outline='#2a4660', width=1)
    for a in range(0,360,30):
        t = math.radians(a)
        d.line((cx+math.cos(t)*(r-4),cy+math.sin(t)*(r-4),cx+math.cos(t)*(r+5),cy+math.sin(t)*(r+5)), fill='#3a5d79', width=2)
    art_mask = icon(card['icon'], 210*SCALE)
    art = Image.new('RGBA', art_mask.size, '#314d65')
    art.putalpha(art_mask.point(lambda a: round(a*.65)))
    im.alpha_composite(art, (int((cx-105)*SCALE), int((cy-105)*SCALE)))
    d = ArtDraw(im)
    for j in range(5):
        x = w-74+j*8
        d.line((x,h-37,x+11,h-48), fill='#3a5b74', width=2)
    # Main action icon and text are deliberately quieter than the focus outline.
    mask = icon(card['icon'], 112*SCALE)
    foreground = Image.new('RGBA', mask.size, CYAN)
    foreground.putalpha(mask)
    im.alpha_composite(foreground, (37*SCALE,32*SCALE))
    d = ArtDraw(im)
    title_size = 76 if name == 'melee' else 68 if name == 'spirits' else 64
    title_font = font(title_size, 'BarlowCondensed-ExtraBoldItalic.ttf')
    while d.textlength(card['title'], font=title_font) > w-100:
        title_size -= 1
        title_font = font(title_size, 'BarlowCondensed-ExtraBoldItalic.ttf')
    d.text((45,172), card['title'], font=title_font, fill=WHITE, stroke_width=0)
    d.text((48,265), card['subtitle'], font=font(27), fill='#9aafc3')
    if name == 'colle':
        d.rounded_rectangle((48,318,224,347), radius=7, fill='#243d50', outline='#3a607c')
        d.text((61,321), 'COMING SOON', font=font(18, 'Barlow-SemiBold.ttf'), fill='#a3cee7')
    else:
        labels = {'melee': '01 / LOCAL', 'other': '02 / SYSTEM', 'spirits': '03 / CONNECT'}
        label = labels[name]
        d.text((w-42-d.textlength(label,font=font(18)),31), label, font=font(18), fill='#6c91af')
    # Real transparent rounded corners, not a rectangular picture over the mask.
    alpha = Image.new('L', im.size)
    ad = ArtDraw(alpha)
    ad.rounded_rectangle((0,0,w-1,h-1), radius=geo['radius'], fill=255)
    im.putalpha(alpha)
    d.rounded_rectangle((1,1,w-2,h-2), radius=geo['radius'], outline='#35516b', width=2)
    return im


def chrome_art():
    """Background and chrome; the native background picture draws this first."""
    yy, xx = np.mgrid[:1080, :1920]
    glow = np.exp(-((xx-1550)**2/1100**2 + (yy-80)**2/900**2))
    colours = np.stack([9+3*glow,14+7*glow,21+11*glow,np.full_like(glow,255)],axis=-1)
    im = Image.fromarray(colours.astype('uint8'), 'RGBA').resize((1920*SCALE,1080*SCALE), Image.Resampling.BICUBIC)
    d = ArtDraw(im)
    # A calm navy surface: no enlarged watermark, dots or artificial grain.
    d.line((64,166,1856,166), fill='#233448', width=1)
    d.line((64,982,1856,982), fill='#1c2d3e', width=1)
    d.text((1410,83), 'SSBU ARENA', font=font(34, 'Barlow-SemiBold.ttf'), fill=WHITE)
    d.text((1410,125), 'COMPETITIVE EDITION', font=font(22), fill='#7594ad')
    d.rounded_rectangle((1326,88,1382,144),radius=14,fill='#162c42',outline='#365c79',width=2)
    d.ellipse((1344,98,1364,118), fill=CYAN)
    d.rounded_rectangle((1337,121,1371,137),radius=7,fill=CYAN)
    # Controller legend stays outside all four native hit regions.
    for x, letter, label in ((1510,'A','Select'), (1712,'B','Back')):
        d.ellipse((x,1004,x+35,1039),fill='#a9c3d7')
        d.text((x+10,1008),letter,font=font(21,'Barlow-Bold.ttf'),fill='#0c1725')
        d.text((x+49,1004),label,font=font(25),fill='#a9bed0')
    return im


