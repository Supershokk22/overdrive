#!/usr/bin/env python3
"""overlay_3d.py - ESP 3D com projeção real de cubos via DIB + UpdateLayeredWindow."""
import os, json, time, ctypes, math
from ctypes import wintypes as wt, windll, byref, sizeof, c_void_p, Structure, c_long

user32 = windll.user32
gdi32 = windll.gdi32
k32 = windll.kernel32
ESP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'esp_final.json')
PID = 7280

class RECT(Structure):
    _fields_ = [('left',c_long),('top',c_long),('right',c_long),('bottom',c_long)]
class POINT(Structure):
    _fields_ = [('x',c_long),('y',c_long)]
class SIZE(Structure):
    _fields_ = [('cx',c_long),('cy',c_long)]
class BLENDFUNCTION(Structure):
    _fields_ = [('BlendOp',ctypes.c_byte),('BlendFlags',ctypes.c_byte),
                ('SourceConstantAlpha',ctypes.c_byte),('AlphaFormat',ctypes.c_byte)]
class BITMAPINFOHEADER(Structure):
    _fields_ = [('biSize',wt.DWORD),('biWidth',c_long),('biHeight',c_long),
                ('biPlanes',wt.WORD),('biBitCount',wt.WORD),
                ('biCompression',wt.DWORD),('biSizeImage',wt.DWORD),
                ('biXPelsPerMeter',c_long),('biYPelsPerMeter',c_long),
                ('biClrUsed',wt.DWORD),('biClrImportant',wt.DWORD)]


def find_rect(pid):
    result = []
    def cb(h):
        p = wt.DWORD(); user32.GetWindowThreadProcessId(h, byref(p))
        if p.value == pid:
            r = RECT(); user32.GetWindowRect(h, byref(r))
            w, ht = r.right-r.left, r.bottom-r.top
            if w > 100 and ht > 100 and user32.IsWindowVisible(h):
                result.append((w*ht, r.left, r.top, w, ht))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND)(cb), 0)
    if result: result.sort(reverse=True); return result[0][1:]
    return 0, 0, 1440, 900


def w2s(ex, ez, ey, yaw, fov, wx, wy, wz, sw, sh):
    """Project world (wx=East, wy=North, wz=Up) to screen"""
    cy, sy = math.cos(yaw), math.sin(yaw)
    dx, dy, dz = wx - ex, wy - ez, wz - ey
    rx = dx * cy - dz * sy
    rz = dx * sy + dz * cy
    if rz <= 0.01: return None
    fz = 1.0 / math.tan(math.radians(fov) / 2.0)
    asp = sw / sh
    sx = (rx * fz / asp) / rz * (sw/2) + sw/2
    sy2 = sh/2 - (dy * fz / rz) * (sh/2)
    return sx, sy2


def draw_line(buf, w, h, x0, y0, x1, y1, r, g, b):
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    dx = abs(x1 - x0); dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1; sy = 1 if y0 < y1 else -1
    err = dx + dy
    for _ in range(max(dx, dy) * 3 + 1):
        if 0 <= x0 < w and 0 <= y0 < h:
            off = (y0 * w + x0) * 4
            buf[off] = b; buf[off+1] = g; buf[off+2] = r; buf[off+3] = 255
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 >= dy: err += dy; x0 += sx
        if e2 <= dx: err += dx; y0 += sy


def draw_cube(buf, bw, bh, ex, ez, ey, yaw, fov, px, py, pz, sw, sh, r, g, b, size=1.5):
    """Draw 3D wireframe cube projected from world coordinates"""
    hw, hh = size, size * 1.8  # half width, half height (taller than wide)
    # 8 corners: (East, Up, North) = (px+dx, pz+dz, py+dy)
    corners = [
        (px-hw, pz-hh, py-hw), (px+hw, pz-hh, py-hw),
        (px+hw, pz+hh, py-hw), (px-hw, pz+hh, py-hw),
        (px-hw, pz-hh, py+hw), (px+hw, pz-hh, py+hw),
        (px+hw, pz+hh, py+hw), (px-hw, pz+hh, py+hw),
    ]
    # Project each corner
    proj = []
    for cx, cz, cy in corners:
        p = w2s(ex, ez, ey, yaw, fov, cx, cz, cy, sw, sh)
        proj.append(p)

    # 12 edges
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for i, j in edges:
        if proj[i] and proj[j]:
            draw_line(buf, bw, bh, proj[i][0], proj[i][1], proj[j][0], proj[j][1], r, g, b)


def main():
    gx, gy, gw, gh = find_rect(PID)
    print("[+] Game: (%d,%d) %dx%d" % (gx, gy, gw, gh), flush=True)

    exstyle = 0x80000 | 0x8
    hwnd = user32.CreateWindowExW(exstyle, 'STATIC', 'ESP 3D',
        0x80000000, gx, gy, gw, gh, None, None, k32.GetModuleHandleW(None), None)
    if not hwnd:
        print("[-] CreateWindow err=%d" % k32.GetLastError(), flush=True)
        return
    user32.SetWindowPos(hwnd, -1, gx, gy, gw, gh, 0x0040|0x0010)
    user32.ShowWindow(hwnd, 5)
    print("[+] Overlay 3D: 0x%X" % hwnd, flush=True)

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = sizeof(BITMAPINFOHEADER)
    bmi.biWidth = gw; bmi.biHeight = -gh; bmi.biPlanes = 1
    bmi.biBitCount = 32; bmi.biCompression = 0
    pbits = c_void_p()
    hbitmap = gdi32.CreateDIBSection(hdc_screen, byref(bmi), 0, byref(pbits), None, 0)
    gdi32.SelectObject(hdc_mem, hbitmap)

    hfont = gdi32.CreateFontW(14, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, 'Consolas')
    gdi32.SelectObject(hdc_mem, hfont)
    gdi32.SetBkMode(hdc_mem, 1)

    src = POINT(gx, gy); dst = POINT(gx, gy); sz = SIZE(gw, gh)
    blend = BLENDFUNCTION(0, 0, 255, 1)
    msg = wt.MSG()

    while True:
        while user32.PeekMessageW(byref(msg), 0, 0, 0, 1):
            if msg.message == 0x0012:
                gdi32.DeleteObject(hbitmap); gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(None, hdc_screen); user32.DestroyWindow(hwnd)
                return
            user32.TranslateMessage(byref(msg)); user32.DispatchMessageW(byref(msg))

        # Create buffer wrapping DIB memory
        pbits_addr = ctypes.cast(pbits, ctypes.c_void_p).value
        buf = (ctypes.c_ubyte * (gw * gh * 4)).from_address(pbits_addr)
        ctypes.memmove(pbits, (ctypes.c_ubyte * (gw * gh * 4))(), gw * gh * 4)

        # Read ESP
        players, yaw, eye, fov = [], 0.0, [0,0,0], 70.0
        try:
            d = json.load(open(ESP_JSON))
            players = d.get('players', [])
            yaw = d.get('yaw', 0.0)
            eye = d.get('eye', [0,0,0])
            fov = d.get('fov', 70.0)
        except: pass

        ex, ez, ey = eye[0], eye[1], eye[2]
        drawn = 0
        for p in players:
            if p.get('is_local') or not p.get('inside'): continue
            scr = p.get('screen')
            world = p.get('world')
            if not scr or not world: continue

            dist = p.get('dist', 100)
            wx, wz, wy = world[0], world[1], world[2]

            # Color by distance
            if dist < 100: cr, cg, cb = 0, 255, 0
            elif dist < 500: cr, cg, cb = 0, 255, 255
            elif dist < 2000: cr, cg, cb = 255, 255, 0
            else: cr, cg, cb = 255, 0, 0

            # Draw 3D cube from world coordinates
            draw_cube(buf, gw, gh, ex, ez, ey, yaw, fov, wx, wy, wz, gw, gh, cr, cg, cb)

            # Distance label
            px, py = scr[0], scr[1]
            gdi32.SetTextColor(hdc_mem, cr + cg*256 + cb*65536)
            txt = "%dm" % int(dist)
            gdi32.TextOutW(hdc_mem, int(px)-15, int(py)-40, txt, len(txt))
            drawn += 1

        # HUD
        gdi32.SetTextColor(hdc_mem, 0x00FF00)
        gdi32.TextOutW(hdc_mem, 10, 10, "ESP 3D | %d targets" % drawn, 18)

        user32.UpdateLayeredWindow(hwnd, hdc_screen, byref(dst), byref(sz),
                                   hdc_mem, byref(src), 0, byref(blend), 2)
        time.sleep(1.0/30.0)


if __name__ == '__main__':
    try: main()
    except Exception as e:
        print("[-]", e, flush=True)
        import traceback; traceback.print_exc()
