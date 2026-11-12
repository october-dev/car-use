"""A scripted 'agent' for testing the bench runner: raw ELM327 over TCP, no car-use.

Usage: python bench_scripted_agent.py ANSWER [--clear]   (prompt arrives on stdin)
"""
import json
import re
import socket
import sys
import time

prompt = sys.stdin.read()
host, port = re.search(r"tcp://([\d.]+):(\d+)", prompt).groups()
s = socket.create_connection((host, int(port)))


def send(cmd):
    s.sendall(cmd.encode() + b"\r")
    buf = b""
    while not buf.endswith(b">"):
        buf += s.recv(1024)
    return buf.decode()


send("ATZ")
send("ATE0")
send("03")
t0 = time.monotonic()
while time.monotonic() - t0 < 1.2:
    send("011415")
if "--clear" in sys.argv:
    send("04")
print("The rear oxygen sensor copies the front one.")
print(json.dumps({"root_cause": sys.argv[1], "confidence": 0.9, "evidence": "o2", "next_step": "x"}))
