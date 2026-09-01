#!/usr/bin/env python3
"""w2s_math.py - World-to-Screen via construcao matematica da ViewProj.
Nao precisa encontrar a ViewProj em memoria — calcula a partir de:
  - posicao do player (heap scan)
  - yaw da camera (+0x258 do camera obj)
  - fov da camera (+0x2C4 do camera obj)
  - pitch = 0 (mapa vazio, plano)

Convencao Arma 3: X=East, Y=Up, Z=North
Camera yaw=0 -> olhando Norte (+Z)
Yaw cresce horario (olhando Leste = yaw pi/2)
"""
import struct, sys, math, json, time
sys.path.insert(0, r'C:\Users\shokk123\Desktop\overdriver')
import mem_core as mc

PID = 14800
MOD = 0x7FF7088C0000
PLAYER = 0x1B871F6C1F0
CAMERA = 0x1B8A8D2C200  # de player+0x0C8
SCREEN_W, SCREEN_H = 1440, 900


def read_cam_data(eng):
    """Le yaw, fov, pitch, altura da camera obj e pos do player."""
    # player pos: struct [X, Z_height, Y_north]
    raw_p = eng.read(PLAYER, 0x10)
    px = struct.unpack_from('<f', raw_p, 0x0)[0]   # X (East, ground)
    pz = struct.unpack_from('<f', raw_p, 0x4)[0]   # Z_height (UP, vertical)
    py = struct.unpack_from('<f', raw_p, 0x8)[0]   # Y_north (North, ground)
    # camera data
    raw_c = eng.read(CAMERA + 0x250, 0x80)
    yaw = struct.unpack_from('<f', raw_c, 0x258 - 0x250)[0]   # +0x258
    fov = struct.unpack_from('<f', raw_c, 0x2C4 - 0x250)[0]   # +0x2C4
    # pitch: tentar ler de offsets possiveis
    # TODO: encontrar pitch real, por agora 0
    pitch = 0.0
    return px, py, pz, yaw, pitch, fov

def w2s(px, py, pz, yaw, pitch, fov_deg, wx, wy, wz, screen_w=SCREEN_W, screen_h=SCREEN_H):
    """Computa W2S para um ponto world (wx, wy, wz).
    Camera em (px, py, pz) com yaw, pitch, fov.
    Retorna (screen_x, screen_y) ou None se offscreen.
    """
    # view direction
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    cp = math.cos(pitch)
    sp = math.sin(pitch)

    # view matrix (column-major, M*p convention)
    # right = (cy, 0, -sy)
    # up = (0, cp, sp)  -- rotated by pitch
    # forward = (sy*cp, sp, cy*cp)  -- no wait
    # Forward in Arma: direction camera looks = (sin(yaw)*cos(pitch), sin(pitch), cos(yaw)*cos(pitch))
    # But we need the VIEW matrix that transforms world->view

    # Translation to camera origin
    dx = wx - px
    dy = wy - py
    dz = wz - pz

    # Rotate to view space: first by -yaw around Y, then by -pitch around X
    # After -yaw rotation:
    rx = dx * cy + dz * (-sy)   # right component
    ry = dy
    rz = dx * sy + dz * cy      # forward component

    # After -pitch rotation (around X):
    vx = rx
    vy = ry * cp + rz * sp
    vz = -ry * sp + rz * cp

    if vz <= 0.01:
        return None  # behind camera

    # Projection
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    aspect = screen_w / screen_h

    ndc_x = (vx * f / aspect) / vz
    ndc_y = (vy * f) / vz

    # Map NDC to screen
    sx = ndc_x * (screen_w / 2.0) + (screen_w / 2.0)
    sy_scr = (screen_h / 2.0) - ndc_y * (screen_h / 2.0)

    return sx, sy_scr


def main():
    s = mc.Session()
    s.attach(PID, 'arma3_x64.exe')
    s.driver.open()
    s.driver.enabled = True
    eng = s.engine

    px, py, pz, yaw, pitch, fov = read_cam_data(eng)
    # px=X, py=Y_north(ground), pz=Z_height(UP)
    print("[+] player=(X %.2f, UP %.2f, N %.2f) yaw=%.3f rad (%.1f deg) fov=%.1f" % (
        px, pz, py, yaw, math.degrees(yaw), fov))

    # Na convencao w2s: (wx, wy=UP, wz=NORTH)
    cam_x, cam_up, cam_north = px, pz, py

    print("\n=== teste W2S com pontos de referencia ===")
    test_pts = [
        ("player", cam_x, cam_up, cam_north),
        ("100m North", cam_x, cam_up, cam_north + 100),
        ("100m South", cam_x, cam_up, cam_north - 100),
        ("100m East", cam_x + 100, cam_up, cam_north),
        ("100m West", cam_x - 100, cam_up, cam_north),
        ("100m Up", cam_x, cam_up + 100, cam_north),
    ]
    fwd_x = math.sin(yaw)
    fwd_n = math.cos(yaw)
    test_pts.append(("100m Forward", cam_x + 100 * fwd_x, cam_up, cam_north + 100 * fwd_n))
    test_pts.append(("100m Backward", cam_x - 100 * fwd_x, cam_up, cam_north - 100 * fwd_n))

    for name, wx, wy, wz in test_pts:
        r = w2s(cam_x, cam_up, cam_north, yaw, pitch, fov, wx, wy, wz)
        if r:
            print("  %s: screen=(%.1f, %.1f)" % (name, r[0], r[1]))
        else:
            print("  %s: OFFSCREEN" % name)

    # Salvar camera data
    json.dump({
        "player": [px, py, pz],
        "yaw": yaw,
        "pitch": pitch,
        "fov": fov,
        "camera_obj": hex(CAMERA),
        "player_obj": hex(PLAYER),
    }, open('cam_math.json', 'w'), indent=2)
    print("\n[+] saved cam_math.json")


if __name__ == '__main__':
    main()
