#!/usr/bin/env python3
"""
Simple network placement client for the tower defense host.

Usage:
    python net_client.py --host HOST_IP --port 9999

Then type commands:
    SUBSCRIBE
    BUY_TOWER <owner> <x> <y> <type>
    PLACE_SPAWNER <owner> <x> <y>
    UPGRADE_TOWER <x> <y>
    START
    RESET

This client sends text commands terminated with newline to the host.
"""
import argparse
import socket
import threading
import sys

def sender_loop(sock):
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            try:
                sock.sendall((line + "\n").encode("utf-8"))
            except BrokenPipeError:
                print("Disconnected from host.")
                break
    except KeyboardInterrupt:
        pass

def receiver_loop(sock):
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            print("[HOST]", data.decode("utf-8").strip())
    except:
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="Host IP")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((args.host, args.port))
    except Exception as e:
        print("Could not connect to host:", e)
        sys.exit(1)
    print("Connected. Type commands or SUBSCRIBE to receive state.")
    t_recv = threading.Thread(target=receiver_loop, args=(sock,), daemon=True)
    t_recv.start()
    try:
        sender_loop(sock)
    finally:
        sock.close()

if __name__ == "__main__":
    main()