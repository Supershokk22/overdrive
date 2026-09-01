#!/usr/bin/env python3
"""runner.py - Engine loop + overlay."""
import subprocess, sys, time, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'w2s_engine.py')
OVERLAY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overlay_pro.py')

# Start overlay
print("[+] Starting overlay...", flush=True)
overlay = subprocess.Popen([sys.executable, OVERLAY], creationflags=0x08)
print("[+] Overlay PID: %d" % overlay.pid, flush=True)
time.sleep(1)

# Engine loop
print("[+] Engine loop starting...", flush=True)
frame = 0
while True:
    try:
        r = subprocess.run([sys.executable, ENGINE], capture_output=True, text=True, timeout=60)
        out = r.stdout.strip().splitlines()
        if out:
            print("[F%d] %s" % (frame, out[-1]), flush=True)
        if r.stderr:
            for line in r.stderr.strip().splitlines()[-2:]:
                print("[F%d ERR] %s" % (frame, line), flush=True)
        frame += 1
    except subprocess.TimeoutExpired:
        print("[F%d] TIMEOUT" % frame, flush=True)
    except Exception as e:
        print("[F%d] ERROR: %s" % (frame, e), flush=True)
    time.sleep(0.5)
