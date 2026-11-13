#!/usr/bin/env python3
"""Mock TaskLot Mega. Opens a pty, speaks the board's EXACT serial lines,
captures what the daemon writes back, and checks it."""
import os, pty, time, subprocess, sys, re, select, termios, tty

BOOT = [
 "=== TaskLot v2 - four spaces, a speaker, a pickup lane ===",
 "space 1 reader (SS 44): 0x92   ok - genuine",
 "speaker reader (SS 37): 0x92   ok - genuine",
 "pickup  reader (SS 36): 0x92   ok - genuine",
 "LCD: 0x27",
 "--------------------","1>-","2>-","3>-","4>-","--------------------",
]

master, slave = pty.openpty()
# CRITICAL: turn OFF echo, or the pty parrots our own writes back and the
# capture looks like the daemon replied when it never did.
a = termios.tcgetattr(slave)
a[3] = a[3] & ~termios.ECHO & ~termios.ECHONL & ~termios.ICANON
termios.tcsetattr(slave, termios.TCSANOW, a)
port = os.ttyname(slave)
env = dict(os.environ,
           TASKLOT_PORT=port,
           TASKLOT_FAKE_TRANSCRIPT="email the professor about the final project")
p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasklot_ears.py")],
                     env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(4)

captured = []
def say(line, wait=0.5):
    os.write(master, (line + "\r\n").encode()); time.sleep(wait)
    drain()
def drain():
    while select.select([master], [], [], 0.15)[0]:
        try: d = os.read(master, 4096).decode(errors="replace")
        except OSError: return
        if d: captured.append(d)

for b in BOOT: say(b, 0.05)

print(">>> SCENARIO 1: blank car orders, then parks")
say("SPEAKER  CAR 3 ordering", 1.0)
say("SPACE 2  <- CAR 3 parked", 4.0)

print(">>> SCENARIO 2: loaded car returns to speaker (read-back)")
say("PLAYBACK CAR 3 reading back", 2.0)

print(">>> SCENARIO 3: park with NO active recording (must not crash/send)")
say("SPACE 4  <- CAR 1 parked", 1.5)

print(">>> SCENARIO 4: pickup clears the task")
say("PICKUP   CAR 3 collected", 1.0)
say("PLAYBACK CAR 3 reading back", 2.0)

print(">>> SCENARIO 5: garbage + partial lines (must not kill the loop)")
say("3>Charge baCAR 4 Glu", 0.4)
say("", 0.3)
say("SPEAKER  CAR 2 ordering", 0.8)
say("SPACE 1  <- CAR 2 parked", 4.0)

time.sleep(1); drain()
p.terminate()
try: out = p.communicate(timeout=5)[0]
except Exception: p.kill(); out = ""

sent = "".join(captured)
print("\n================ WHAT THE DAEMON WROTE TO THE BOARD ================")
print(repr(sent))
print("\n================ DAEMON LOG ================")
print(out[-3000:])

print("\n================ CHECKS ================")
cmds = re.findall(r"CAR \d+ [^\r\n]*", sent)
ok = True
def chk(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name); ok = ok and cond
chk("sent a CAR command for car 3", any(c.startswith("CAR 3 ") for c in cmds))
chk("sent a CAR command for car 2", any(c.startswith("CAR 2 ") for c in cmds))
chk("did NOT send anything for car 1 (no recording active)",
    not any(c.startswith("CAR 1 ") for c in cmds))
chk("LCD text <= 18 chars", all(len(c.split(" ",2)[2]) <= 18 for c in cmds if len(c.split(" ",2))>2))
chk("daemon still alive through garbage (reached scenario 5)",
    any(c.startswith("CAR 2 ") for c in cmds))
chk("commands are newline-terminated", sent.count("\n") >= len(cmds))
print("\nCOMMANDS SENT:", cmds)
print("\nRESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
