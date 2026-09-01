#!/usr/bin/env python3
"""
w2s_engine.py - ESP Arma 3 multiplayer - VERSAO OTIMIZADA
- Scan rapido de players via vtable
- Yaw via brute-force (testa todos, pick best)
- Runner loop integrado
"""
import os,sys,time,struct,math,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from mem_core import Session

PID=7280
EXE='arma3_x64.exe'
MOD=0x7FF7088C0000
VTABLE_RVA=0x1C18CA8
VT_OFF=0xD0
CHUNK=0x10000  # bigger chunks = faster scan

def rd(a,n,eng):
    try: d=eng.read(a,n); return d if d and len(d)==n else None
    except: return None

def q(a,eng):
    d=rd(a,8,eng)
    return struct.unpack('<Q',d)[0] if d and len(d)==8 else 0

def fval(a,eng):
    d=rd(a,4,eng)
    return struct.unpack('<f',d)[0] if d and len(d)==4 else None

def find_game_rect():
    import ctypes,ctypes.wintypes as wt
    user32=ctypes.windll.user32
    class RECT(ctypes.Structure):
        _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
    result=[]
    def cb(hwnd):
        pid=wt.DWORD(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==PID:
            r=RECT(); user32.GetWindowRect(hwnd,ctypes.byref(r))
            w=r.right-r.left; h=r.bottom-r.top
            if w>50 and h>50 and user32.IsWindowVisible(hwnd):
                result.append((w*w+h*h,w,h))
        return True
    CB=ctypes.WINFUNCTYPE(ctypes.c_bool,wt.HWND)
    user32.EnumWindows(CB(cb),0)
    if result: result.sort(reverse=True); return (result[0][1],result[0][2])
    return (1440,900)

def project(eyex, eyez, eyey, yaw, fov_deg, wx, wy, wz, sw, sh):
    cy=math.cos(yaw); sy=math.sin(yaw)
    dx=wx-eyex; dy=wy-eyez; dz=wz-eyey
    rx=dx*cy-dz*sy; rz=dx*sy+dz*cy
    if rz<=0.01: return None
    fz=1.0/math.tan(math.radians(fov_deg)/2.0)
    asp=sw/sh
    ndx=(rx*fz/asp)/rz; ndy=(dy*fz)/rz
    return (ndx*(sw/2)+sw/2, sh/2-ndy*(sh/2))

def scan_players(eng):
    """Fast player scan via vtable pattern"""
    import ctypes,ctypes.wintypes as wt
    k32=ctypes.windll.kernel32
    MEM_COMMIT=0x1000; RP=0x02|0x04|0x08|0x10|0x20|0x40|0x80; PRIV=0x20000
    class MBI(ctypes.Structure):
        _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),
                  ('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),
                  ('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD)]
    hproc=k32.OpenProcess(0x1F0FFF,False,PID)
    regions=[]; addr=0
    while addr<0x7FFFFFFFF000:
        mbi=MBI(); r=k32.VirtualQueryEx(hproc,ctypes.c_void_p(addr),ctypes.byref(mbi),ctypes.sizeof(mbi))
        if not r: break
        if mbi.State==MEM_COMMIT and (mbi.Protect&RP) and mbi.Type==PRIV and mbi.RegionSize>=0x1000:
            regions.append((mbi.BaseAddress,mbi.RegionSize))
        nxt=(mbi.BaseAddress or 0)+mbi.RegionSize
        if nxt<=addr or mbi.RegionSize==0: break
        addr=nxt
    k32.CloseHandle(hproc)

    vtpack=struct.pack('<Q',MOD+VTABLE_RVA)
    players=[]
    for base,sz in regions:
        pos=base; lim=base+sz
        while pos<lim:
            raw=r(pos,CHUNK,eng)
            if not raw: pos+=CHUNK; continue
            idx=0
            while True:
                fnd=raw.find(vtpack,idx)
                if fnd<0 or fnd+VT_OFF>len(raw): break
                bs=pos+fnd-VT_OFF
                xb=rd(bs,12,eng)
                if xb and len(xb)==12:
                    x,z,y=struct.unpack('<3f',xb)
                    if abs(x)<100000 and abs(y)<100000 and -10<=z<2000:
                        cam=q(bs+0x0C8,eng)
                        # Read yaw from +0x2F8->+0x200
                        yaw=None
                        ptr_data=rd(bs+0x2F8,8,eng)
                        if ptr_data:
                            ptr=struct.unpack('<Q',ptr_data)[0]
                            if ptr>0x1000:
                                yv=fval(ptr+0x200,eng)
                                if yv is not None and -6.3<yv<6.3 and abs(yv)>0.01:
                                    yaw=yv
                        players.append({'base':bs,'x':x,'z':z,'y':y,'cam':cam,'yaw':yaw})
                idx=fnd+1
            pos+=CHUNK
    
    # Dedup
    dedup=[]; seen=set()
    for p in players:
        k=(round(p['x'],0),round(p['y'],0))
        if k in seen: continue
        seen.add(k); dedup.append(p)
    return dedup[:100]

def find_best_local(players, sw, sh, fov):
    """Try each player with valid yaw as local, pick best"""
    yaw_players=[(i,p) for i,p in enumerate(players) if p['yaw'] is not None]
    if not yaw_players:
        return 0,0.0
    
    best_inside=0; best_idx=0; best_yaw=0.0
    for idx,p in yaw_players:
        lp=players[idx]
        eyex,eyeu,eyen=lp['x'],lp['z']+1.5,lp['y']
        inside=0
        for i,pl in enumerate(players):
            if i==idx: continue
            r=project(eyex,eyeu,eyen,p['yaw'],fov,pl['x'],pl['z'],pl['y'],sw,sh)
            if r and 0<r[0]<sw and 0<r[1]<sh:
                inside+=1
        if inside>best_inside:
            best_inside=inside; best_idx=idx; best_yaw=p['yaw']
    return best_idx, best_yaw

def main():
    s=Session(); s.attach(PID,EXE); s.driver.open(); s.driver.enabled=True
    eng=s.engine

    players=scan_players(eng)
    if not players:
        print("[-] NO PLAYERS"); return

    SW,SH=find_game_rect()
    fov=100.0

    # Find best local
    best_idx, best_yaw = find_best_local(players, SW, SH, fov)
    lp=players[best_idx]

    # Project all
    eyex,eyeu,eyen=lp['x'],lp['z']+1.5,lp['y']
    out=[]
    inside_count=0
    for i,p in enumerate(players):
        r=project(eyex,eyeu,eyen,best_yaw,fov,p['x'],p['z'],p['y'],SW,SH)
        d=((p['x']-eyex)**2+(p['z']-eyeu)**2+(p['y']-eyen)**2)**0.5
        is_in=False
        if r and 0<r[0]<SW and 0<r[1]<sh:
            is_in=True; inside_count+=1
        out.append({'base':'0x%X'%p['base'],
                    'screen':[round(r[0],1),round(r[1],1)] if r else None,
                    'dist':round(d,1),'inside':is_in,
                    'is_local':(i==best_idx)})

    json.dump({'players':out,'method':'brute_yaw',
               'eye':[eyex,eyeu,eyen],'yaw':best_yaw,'pitch':0,'fov':fov,
               'local':'0x%X'%lp['base']},
              open('esp_final.json','w'),indent=2)
    print("[+] %d players, %d inside, yaw=%.1f deg, local=0x%X pos=(%.0f,%.0f)"%(
        len(players),inside_count,math.degrees(best_yaw),lp['base'],lp['x'],lp['y']))

if __name__=='__main__':
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc()
        print("[-]",e)
