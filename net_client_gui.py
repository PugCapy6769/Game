```markdown
#!/usr/bin/env python3
"""
Networked GUI client that subscribes to the host's JSON state feed and renders it.
Also provides a simple shop UI for buying towers and placing spawners.

Run:
    python net_client_gui.py --host HOST_IP --port 9999

Controls:
    Left-click: place selected item (BUY_TOWER or PLACE_SPAWNER) at click position (sends command)
    1/2: set owner (player 1 or 2) for buy commands
    T/G: cycle tower types
    U: send UPGRADE_TOWER <x> <y> for tower under mouse
    ENTER: send START
    R: send RESET
    ESC: quit
"""
import argparse
import json
import socket
import threading
import time
import pygame
import sys

# Default visuals (keep in sync with host constants for readability)
WIDTH, HEIGHT = 1000, 640
BASE_POS = (WIDTH - 60, HEIGHT // 2)
BASE_RADIUS = 36

# Colors
WHITE = (255, 255, 255)
BLACK = (8, 8, 8)
GRAY = (160, 160, 160)
GREEN = (80, 200, 80)
RED = (220, 70, 70)
BLUE = (80, 140, 240)
YELLOW = (240, 200, 30)
ORANGE = (245, 145, 30)
PURPLE = (170, 80, 200)

# Tower types shown in-shop
TOWER_TYPES = ["basic", "sniper", "rapid"]

class NetClientGUI:
    def __init__(self, host, port):
        pygame.init()
        pygame.display.set_caption("Tower Defense - Network Client")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 16)
        self.bigfont = pygame.font.SysFont("consolas", 28)

        self.host = host
        self.port = port
        self.sock = None
        self.running = True
        self.state = {}
        self.state_lock = threading.Lock()

        # shop / control
        self.owner = 1
        self.selected_tower_type = "basic"
        self.mode = "buy_tower"  # or "place_spawner"
        self.subscribed = False

    def connect_and_subscribe(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.host, self.port))
            # start receiver thread
            t = threading.Thread(target=self.receiver_loop, daemon=True)
            t.start()
            # subscribe
            self.send_cmd("SUBSCRIBE")
            self.subscribed = True
            print("[CLIENT] Subscribed to host state")
        except Exception as e:
            print("Could not connect:", e)
            self.running = False

    def send_cmd(self, txt: str):
        if not self.sock:
            return
        try:
            self.sock.sendall((txt.strip() + "\n").encode("utf-8"))
        except Exception as e:
            print("[CLIENT] send error:", e)
            self.running = False

    def receiver_loop(self):
        buf = b""
        try:
            while self.running:
                data = self.sock.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        snap = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    with self.state_lock:
                        self.state = snap
        except Exception:
            pass
        finally:
            print("[CLIENT] disconnected from host")
            self.running = False

    def run(self):
        self.connect_and_subscribe()
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                        break
                    if event.key == pygame.K_1:
                        self.owner = 1
                    if event.key == pygame.K_2:
                        self.owner = 2
                    if event.key == pygame.K_t:
                        idx = TOWER_TYPES.index(self.selected_tower_type)
                        self.selected_tower_type = TOWER_TYPES[(idx + 1) % len(TOWER_TYPES)]
                    if event.key == pygame.K_g:
                        idx = TOWER_TYPES.index(self.selected_tower_type)
                        self.selected_tower_type = TOWER_TYPES[(idx - 1) % len(TOWER_TYPES)]
                    if event.key == pygame.K_u:
                        mx, my = pygame.mouse.get_pos()
                        self.send_cmd(f"UPGRADE_TOWER {mx} {my}")
                    if event.key == pygame.K_RETURN:
                        self.send_cmd("START")
                    if event.key == pygame.K_r:
                        self.send_cmd("RESET")
                    if event.key == pygame.K_TAB:
                        # toggle mode
                        self.mode = "place_spawner" if self.mode == "buy_tower" else "buy_tower"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    if self.mode == "buy_tower":
                        self.send_cmd(f"BUY_TOWER {self.owner} {mx} {my} {self.selected_tower_type}")
                    else:
                        self.send_cmd(f"PLACE_SPAWNER {self.owner} {mx} {my}")

            self.draw()
            pygame.display.flip()
            self.clock.tick(60)

        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        pygame.quit()

    def draw(self):
        self.screen.fill((34, 36, 48))
        # draw base path hint
        pygame.draw.line(self.screen, (60, 60, 80), (0, HEIGHT // 2), BASE_POS, 24)
        # snapshot copy
        with self.state_lock:
            snap = dict(self.state)
        # obstacles
        for ob in snap.get("obstacles", []):
            r = pygame.Rect(ob["x"], ob["y"], ob["w"], ob["h"])
            pygame.draw.rect(self.screen, (90, 90, 100), r)
        # base
        pygame.draw.circle(self.screen, (60, 200, 120), BASE_POS, BASE_RADIUS)
        pygame.draw.circle(self.screen, (30, 160, 80), BASE_POS, BASE_RADIUS - 8)
        # spawners
        for s in snap.get("spawners", []):
            color = ORANGE if s["owner"] == 1 else RED
            pygame.draw.rect(self.screen, color, (s["x"] - 12, s["y"] - 12, 24, 24))
        # towers
        for t in snap.get("towers", []):
            color = BLUE if t["owner"] == 1 else PURPLE
            pygame.draw.circle(self.screen, color, (int(t["x"]), int(t["y"])), 16)
            lvl = self.font.render(f"L{t.get('level',1)}", True, WHITE)
            self.screen.blit(lvl, (int(t["x"]) - lvl.get_width()//2, int(t["y"]) - lvl.get_height()//2))
        # enemies
        for e in snap.get("enemies", []):
            etype = e.get("etype", "basic")
            color = (255, 120, 80)
            if etype == "fast":
                color = (255, 200, 60)
            elif etype == "armored":
                color = (200, 200, 220)
            pygame.draw.circle(self.screen, color, (int(e["x"]), int(e["y"])), 10)
            # hp bar
            w = 22; h = 4
            x = int(e["x"] - w / 2); y = int(e["y"] - 10 - 10)
            pygame.draw.rect(self.screen, RED, (x, y, w, h))
            maxhp = 30
            if etype in ("fast",):
                maxhp = 18
            if etype in ("armored",):
                maxhp = 70
            hpw = max(0, int((e.get("hp",0) / maxhp) * w))
            pygame.draw.rect(self.screen, GREEN, (x, y, hpw, h))
        # HUD / shop
        self.draw_ui(snap)

    def draw_ui(self, snap):
        # top-left instructions
        lines = [
            f"Mode: {'BUY TOWER' if self.mode=='buy_tower' else 'PLACE SPAWNER'} (TAB to toggle)",
            f"Owner: {self.owner} (press 1 or 2)",
            f"Tower type: {self.selected_tower_type} (T/G to cycle)",
            "Left-click to place. U to upgrade tower under mouse. ENTER to start. R to reset.",
        ]
        for i, l in enumerate(lines):
            r = self.font.render(l, True, WHITE if i == 0 else GRAY)
            self.screen.blit(r, (8, 8 + i * 18))
        money = snap.get("money", {"1":0,"2":0})
        moneytxt = self.font.render(f"P1 Money: ${money.get('1',0)}   P2 Money: ${money.get('2',0)}", True, YELLOW)
        self.screen.blit(moneytxt, (8, HEIGHT - 36))
        rt = snap.get("time_left", 0.0)
        rt_text = self.font.render(f"Time Left: {int(rt)//60:02d}:{int(rt)%60:02d}", True, GREEN)
        self.screen.blit(rt_text, (WIDTH // 2 - rt_text.get_width() // 2, 8))
        # winner
        winner = snap.get("winner", "")
        if winner:
            msg = "TOWERS WIN!" if winner == "TOWERS" else "ENEMIES WIN!"
            header = self.bigfont.render(msg, True, GREEN if winner=="TOWERS" else RED)
            self.screen.blit(header, (WIDTH//2 - header.get_width()//2, HEIGHT//2 - 20))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="Host IP")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()

    client = NetClientGUI(args.host, args.port)
    client.run()

if __name__ == "__main__":
    main()