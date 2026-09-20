#!/usr/bin/env python3
"""Turn the PPMs the preview writes into one PNG to look at.

  sheet.py out.png grid 6 1 portrait landscape idle0 idle1 ...
  sheet.py face.png crop 30 95 180 175 3 portrait idle4
"""
import sys, zlib, struct

def readppm(p):
    d = open(p, 'rb').read(); parts = d.split(b'\n', 3)
    w, h = map(int, parts[1].split()); return w, h, parts[3]

def png(path, w, h, rgb):
    raw = b''.join(b'\x00' + rgb[y*w*3:(y+1)*w*3] for y in range(h))
    def ck(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t+d) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n'
        + ck(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
        + ck(b'IDAT', zlib.compress(raw, 6)) + ck(b'IEND', b''))

def place(out, cells, cw, ch, cols, gap=8):
    rows = (len(cells) + cols - 1) // cols
    W, H = cols*cw + gap*(cols-1), rows*ch + gap*(rows-1)
    buf = bytearray(b'\x18' * (W*H*3))
    for k, rowsrc in enumerate(cells):
        ox, oy = (k % cols)*(cw+gap), (k // cols)*(ch+gap)
        for y in range(ch):
            buf[((oy+y)*W+ox)*3:((oy+y)*W+ox+cw)*3] = rowsrc[y]
    png(out, W, H, bytes(buf))
    print('ok', W, H)

out, mode = sys.argv[1], sys.argv[2]
if mode == 'grid':
    cols, sc = int(sys.argv[3]), int(sys.argv[4]); names = sys.argv[5:]
    w, h, _ = readppm(f'out_{names[0]}.ppm'); cw, ch = w//sc, h//sc
    cells = []
    for n in names:
        w, h, d = readppm(f'out_{n}.ppm')
        cells.append([b''.join(d[((y*sc)*w + x*sc)*3:((y*sc)*w + x*sc)*3+3] for x in range(cw))
                      for y in range(ch)])
    place(out, cells, cw, ch, cols)
else:  # crop x y w h scale names...
    X, Y, CW, CH, S = (int(v) for v in sys.argv[3:8]); names = sys.argv[8:]
    cells = []
    for n in names:
        w, h, d = readppm(f'out_{n}.ppm')
        cells.append([b''.join(d[(min(h-1, Y+y//S)*w + min(w-1, X+x//S))*3:
                                 (min(h-1, Y+y//S)*w + min(w-1, X+x//S))*3+3] for x in range(CW*S))
                      for y in range(CH*S)])
    place(out, cells, CW*S, CH*S, len(names))
