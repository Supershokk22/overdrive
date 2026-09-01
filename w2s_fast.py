#!/usr/bin/env python3
"""
w2s_fast.py - ESP Arma 3 - SCAN RAPIDO POR POSICOES
Estrategia:
1. Scan heap por triplas de float (X,Z,Y) no range do mapa (~2s)
2. Valida cada candidato com vtable em +0xD0 (~0.1ms cada)
3. Re-read posicoes dos enderecos validados (~instantaneo)
4. Yaw via brute-force a cada 3s
Total: ~3-5s por scan completo, ~5ms por frame re-read
"""
import os, sys, time, struct, math, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mem_core import Session

PID = 7280
EXE = 'arma3_x64.exe'
MOD = 0x7FF7088C0000
VT_RVA = 0x1C18CA8
VT_OFF = 0xD0
FOV = 70.0

cached = []  # [(base, x, z, y), ...]
last_scan = 0
cached_yaw = 0.0  # Will be set by brute force
last_yaw = 0


def mr(eng, a, n):
    try:
        d = eng.read(a, n)
        return d if d and len(d) == n else None
    except:
        return None


def find_rect(pid):
    import ctypes, ctypes.wintypes as wt
    from ctypes import c_long
    u32 = ctypes.windll.user32
    class R(ctypes.Structure):
        _fields_ = [('l',c_long),('t',c_long),('r',c_long),('b',c_long)]
    res = []
    def cb(h):
        p = wt.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            r = R(); u32.GetWindowRect(h, ctypes.byref(r))
            w, ht = r.r-r.l, r.b-r.t
            if w > 100 and ht > 100 and u32.IsWindowVisible(h):
                res.append((w*ht, r.l, r.t, w, ht))
        return True
    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND)(cb), 0)
    if res: res.sort(reverse=True); return res[0][1:]
    return 0,0,1440,900


def get_regions(pid):
    import ctypes, ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32
    class MBI(ctypes.Structure):
        _fields_=[('ba',ctypes.c_void_p),('ab',ctypes.c_void_p),
                   ('ap',wt.DWORD),('pi',wt.WORD),('rs',ctypes.c_size_t),
                   ('s',wt.DWORD),('p',wt.DWORD),('t',wt.DWORD)]
    hp = k32.OpenProcess(0x1F0FFF, False, pid)
    regs=[]; a=0
    while a<0x7FFFFFFFF000:
        m=MBI(); r=k32.VirtualQueryEx(hp,ctypes.c_void_p(a),ctypes.byref(m),ctypes.sizeof(m))
        if not r: break
        if m.s==0x1000 and m.t==0x20000 and m.rs>=0x1000:
            if m.p&(0x04|0x08|0x20|0x40|0x80):
                regs.append((m.ba,m.rs))
        n=(m.ba or 0)+m.rs
        if n<=a or m.rs==0: break
        a=n
    k32.CloseHandle(hp)
    return regs


def fast_scan(eng):
    """Scan heap for position triples, validate with vtable"""
    global cached
    regs = get_regions(PID)
    # Only scan game heap range
    regs = [(b,s) for b,s in regs if 0x23000000000 <= b < 0x24000000000]
    
    vt = struct.pack('<Q', MOD + VT_RVA)
    candidates = {}  # addr -> (x,z,y)
    
    CHUNK = 0x10000
    t0 = time.time()
    
    for base, sz in regs:
        pos = base; lim = base + sz
        while pos < lim:
            n = min(CHUNK, lim - pos)
            try: ch = eng.read(pos, n)
            except: pos += n; continue
            if not ch: pos += n; continue
            
            # Find float triples in map range using struct scan
            for off in range(0, len(ch) - 12, 4):
                try:
                    x, z, y = struct.unpack_from('<3f', ch, off)
                except:
                    continue
                # Map coordinate filter
                if 5000 < x < 25000 and 0 <= z <= 300 and 5000 < y < 30000:
                    addr = pos + off
                    candidates[addr] = (x, z, y)
            pos += CHUNK
    
    print("[+] Position scan: %d candidates in %.1fs" % (len(candidates), time.time()-t0), flush=True)
    
    # Validate with vtable check
    validated = []
    for addr, (x, z, y) in candidates.items():
        # Check if vtable is at addr + VT_OFF
        vtable = mr(eng, addr + VT_OFF, 8)
        if vtable and len(vtable) == 8:
            vt_val = struct.unpack('<Q', vtable)[0]
            if vt_val == MOD + VT_RVA:
                validated.append((addr, x, z, y))
    
    cached = validated
    print("[+] Validated: %d players in %.1fs" % (len(cached), time.time()-t0), flush=True)


def find_yaw(players, li, sw, sh):
    lp = players[li]
    ex, ez, ey = lp[1], lp[2]+1.5, lp[3]
    best_sp = -1; best_y = 0
    for deg in range(0, 360, 1):
        yaw = math.radians(deg)
        sl = []
        for i, p in enumerate(players):
            if i == li: continue
            r = proj(ex, ez, ey, yaw, FOV, p[1], p[2]+1.5, p[3], sw, sh)
            if r and 0 < r[0] < sw and 0 < r[1] < sh:
                sl.append(r)
        if len(sl) > 5:
            mx = sum(s[0] for s in sl) / len(sl)
            my = sum(s[1] for s in sl) / len(sl)
            sp = sum((s[0]-mx)**2 + (s[1]-my)**2 for s in sl) * len(sl)
            if sp > best_sp: best_sp = sp; best_y = yaw
    return best_y


def proj(ex, ez, ey, yaw, fov, wx, wy, wz, sw, sh):
    cy, sy = math.cos(yaw), math.sin(yaw)
    dx, dy, dz = wx-ex, wy-ez, wz-ey
    rx = dx*cy - dz*sy
    rz = dx*sy + dz*cy
    if rz <= 0.01: return None
    fz = 1.0 / math.tan(math.radians(fov)/2.0)
    asp = sw/sh
    return ((rx*fz/asp)/rz*(sw/2)+sw/2, sh/2-(dy*fz/rz)*(sh/2))


def filter_cluster(players):
    if len(players) < 5: return players
    cx = sum(p[1] for p in players) / len(players)
    cy = sum(p[3] for p in players) / len(players)
    ds = [math.sqrt((p[1]-cx)**2 + (p[3]-cy)**2) for p in players]
    med = sorted(ds)[len(ds)//2]
    th = max(med * 3, 500)
    return [p for i, p in enumerate(players) if ds[i] < th]


def main():
    global cached, cached_yaw, last_scan, last_yaw
    s = Session(); s.attach(PID, EXE); s.driver.open(); s.driver.enabled=True
    eng = s.engine
    gx,gy,gw,gh = find_rect(PID)
    print("[+] Game %dx%d" % (gw, gh), flush=True)

    scan_done = False
    while True:
        t0 = time.time()

        # Fast scan every 5s (in background)
        if not cached or (t0 - last_scan) > 5:
            fast_scan(eng)
            last_scan = t0

        # Read positions (instant)
        players = []
        for base, x0, z0, y0 in cached:
            xb = mr(eng, base, 12)
            if xb and len(xb) == 12:
                x, z, y = struct.unpack('<3f', xb)
                if abs(x) < 100000 and abs(y) < 100000 and -10 <= z < 2000:
                    players.append((base, x, z, y))

        players = filter_cluster(players)
        if not players:
            time.sleep(0.05); continue

        # Local
        cx = sum(p[1] for p in players) / len(players)
        cy = sum(p[3] for p in players) / len(players)
        li = min(range(len(players)), key=lambda i: (players[i][1]-cx)**2 + (players[i][3]-cy)**2)

        # Yaw: brute force every 3s
        if (t0 - last_yaw) > 3:
            old_yaw = cached_yaw
            cached_yaw = find_yaw(players, li, gw, gh)
            last_yaw = t0
            if abs(math.degrees(cached_yaw) - math.degrees(old_yaw)) > 5:
                print("[+] yaw: %d -> %d deg" % (math.degrees(old_yaw), math.degrees(cached_yaw)), flush=True)

        yaw = cached_yaw
        lp = players[li]
        ex, ez, ey = lp[1], lp[2]+1.5, lp[3]

        out = []; ic = 0
        for i, p in enumerate(players):
            r = proj(ex, ez, ey, yaw, FOV, p[1], p[2]+1.5, p[3], gw, gh)
            d = math.sqrt((p[1]-ex)**2 + (p[2]-ez)**2 + (p[3]-ey)**2)
            is_in = r and 0 < r[0] < gw and 0 < r[1] < gh
            if is_in: ic += 1
            out.append({'base':'0x%X'%p[0],
                        'world':[p[1],p[2]+1.5,p[3]],
                        'screen':[round(r[0],1),round(r[1],1)] if r else None,
                        'dist':round(d,1),'inside':is_in,'is_local':(i==li)})

        json.dump({'players':out,'eye':[ex,ez,ey],'yaw':yaw,'fov':FOV,
                   'local':'0x%X'%lp[0]}, open('esp_final.json','w'))
        dt = (time.time()-t0)*1000
        print("[+] %d/%d yaw=%d %dms" % (ic, len(players), math.degrees(yaw), dt), flush=True)
        time.sleep(0.05)


if __name__=='__main__':
    while True:
        try: main(); break
        except Exception as e:
            import traceback; traceback.print_exc()
            print("[-]", e, flush=True); time.sleep(1)
