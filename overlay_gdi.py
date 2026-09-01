#!/usr/bin/env python3
# overlay_gdi.py — Overlay ESP Ring 3 (STATIC + LWA_COLORKEY).
# Fundo preto = transparente (colorkey). Desenho GDI direto no HDC da janela.
# Overlay STATIC + LWA_COLORKEY.
import os, sys, json, time, ctypes, ctypes.wintypes as wt
user32 = ctypes.windll.user32
gdi32  = ctypes.windll.gdi32
k32    = ctypes.windll.kernel32

# constantes
WS_EX_LAYERED     = 0x80000
WS_EX_TOPMOST     = 0x8
WS_POPUP          = 0x80000000
SWP_SHOWWINDOW    = 0x40
SWP_NOACTIVATE    = 0x10
HWND_TOPMOST      = -1
LWA_COLORKEY      = 1
TRANSPARENT       = 1
WM_QUIT           = 0x0012

ESP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'esp_final.json')

class RECT(ctypes.Structure):
    _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
class MSG(ctypes.Structure):
    _fields_=[('hwnd',ctypes.c_uint),('message',ctypes.c_uint),('wParam',ctypes.c_uint),('lParam',ctypes.c_uint),
              ('time',ctypes.c_uint32),('pt',ctypes.c_long*2)]

def find_game_rect():
    target_pid = 7280
    result=[]
    def cb(hwnd):
        pid=ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==target_pid:
            r=RECT(); user32.GetWindowRect(hwnd,ctypes.byref(r))
            style=user32.GetWindowLongW(hwnd,-16)
            result.append((r.left,r.top,r.right-r.left,r.bottom-r.top,style))
        return True
    CB=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.wintypes.HWND)
    user32.EnumWindows(CB(cb),0)
    if result:
        x,y,w,h,style=result[0]
        borderless = (style & 0x00C00000)==0
        if w>=1900 and h>=1000:
            sys.stderr.write("[!] AVISO: fullscreen EXCLUSIVO — overlay NAO aparece. Use borderless.\n")
        print("[+] jogo: hud=%d rect=(%d,%d) %dx%d borderless=%s"%(0,x,y,w,h,borderless))
        return (x,y,w,h)
    print("[!] jogo nao achado -> fallback 1920x1080")
    return (0,0,1920,1080)

def main():
    x, y, W, H = find_game_rect()
    print("[+] overlay rect = (%d,%d) %dx%d" % (x, y, W, H))

    # ---- cria janela STATIC LAYERED ----
    exstyle = WS_EX_LAYERED | WS_EX_TOPMOST
    hwnd = user32.CreateWindowExW(
        exstyle, 'STATIC', 'ESP', WS_POPUP, x, y, W, H,
        None, None, ctypes.windll.kernel32.GetModuleHandleW(None), None)
    if not hwnd:
        print("[-] CreateWindowExW falhou (err=%d)"%ctypes.windll.kernel32.GetLastError()); return
    user32.ShowWindow(hwnd, 5)
    user32.SetWindowPos(hwnd, -1, x, y, W, H, 0x0040|0x0010)  # SWP_SHOWWINDOW|SWP_NOACTIVATE
    # colorkey: preto (0x000000) = transparente
    user32.SetLayeredWindowAttributes(hwnd, 0x000000, 0, 1)  # LWA_COLORKEY

    hbr_black = gdi32.CreateSolidBrush(0x000000)
    hbr_green = gdi32.CreateSolidBrush(0x00FF00)  # verde para local
    hbr_cyan  = gdi32.CreateSolidBrush(0x00FFFF)  # ciano para amigos

    hfont = gdi32.CreateFontW(16,0,0,0,700,0,0,0,0,0,0,0,0,'Arial')

    running = True
    while running:
        players = []
        if os.path.exists(ESP_JSON):
            try:
                d = json.load(open(ESP_JSON))
                players = d.get('players', [])
            except Exception:
                players = []

        hdc = user32.GetDC(hwnd)
        user32.FillRect(hdc, ctypes.byref(RECT(0,0,W,H)), hbr_black)  # fundo preto = transparente
        oldf = gdi32.SelectObject(hdc, hfont)
        gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
        gdi32.SetTextColor(hdc, 0x00FF00)

        drawn_px = 0
        for p in players:
            scr = p.get('screen')
            if not scr or len(scr) < 2 or not p.get('inside'): continue
            # esp_final.json já entrega coordenadas em pixels da resolução REAL do jogo
            # (w2s_engine projeta direto para 1440x900). Não re-escalar.
            px = int(scr[0]); py = int(scr[1])
            color = 0x00FF00 if p.get('is_local') else 0x00FFFF
            gdi32.SelectObject(hdc, hbr_green if p.get('is_local') else hbr_cyan)
            bw = 12; bh = 24
            gdi32.Rectangle(hdc, px - bw, py - bh, px + bw, py + bh)
            drawn_px += (bw*2) * (bh*2)
            gdi32.MoveToEx(hdc, px, py + bh, None)
            gdi32.LineTo(hdc, px, py + bh + 10)
            dist = p.get('dist')
            if dist is not None:
                txt = "%.0fm" % dist
                gdi32.TextOutW(hdc, px - bw, py - bh - 18, txt, len(txt))
        gdi32.SelectObject(hdc, oldf)
        user32.ReleaseDC(hwnd, hdc)
        user32.UpdateWindow(hwnd)

        # heartbeat
        try:
            with open('overlay_heartbeat.json','w') as _f:
                json.dump({'players':len(players),'drawn_px':drawn_px,
                           'frame':int(time.time()*1000)}, _f)
                _f.flush(); os.fsync(_f.fileno())
        except Exception:
            pass

        time.sleep(1.0/60.0)

    user32.DestroyWindow(hwnd)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("[*] overlay parado")