import argparse
import json
import socket
import threading
import time
import copy
import pygame
import sys

# Visuals synced with host
WIDTH, HEIGHT = 1000, 640
BASE_POS = (WIDTH - 60, HEIGHT // 2)
BASE_RADIUS = 36

WHITE = (255, 255, 255)
BLACK = (8, 8, 8)
GRAY = (160, 160, 160)
GREEN = (80, 200, 80)
RED = (220, 70, 70)
BLUE = (80, 140, 240)
YELLOW = (240, 200, 30)
ORANGE = (245, 145, 30)
PURPLE = (170, 80, 200)

TOWER_TYPES = ["basic", "sniper", "rapid"]


# --------------------------------------------------
# Client class
# --------------------------------------------------
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

        # controls
        self.owner = 1
        self.selected_tower_type = "basic"
        self.mode = "buy_tower"  # or "place_spawner"
        self.subscribed = False

    # --------------------------------------------------
    # Networking
    # --------------------------------------------------
    def connect_and_subscribe(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.host, self.port))
            t = threading.Thread(target=self.receiver_loop, daemon=True)
            t.start()
            self.send_cmd("SUBSCRIBE")
            self.subscribed = True
            print("[CLIENT] Connected & Subscribed")
        except Exception as e:
            print("Connection failed:", e)
            self.running = False

    def send_cmd(self, text):
        if not self.sock:
            return
        try:
            self.sock.sendall((text.strip() + "\n").encode("utf-8"))
        except Exception as e:
            print("[CLIENT] send error:", e)
            self.running = False

    def receiver_loop(self):
        """
        The host guarantees single-line JSON frames ending with '\n'.
        We keep framing simple but safe.
        """
        buf = b""
        try:
            while self.running:
                data = self.sock.recv(65536)
                if not data:
                    break
                buf += data

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        snap = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    with self.state_lock:
                        self.state = snap
        except:
            pass
        finally:
            print("[CLIENT] disconnected")
            self.running = False

    # --------------------------------------------------
    # Main loop
    # --------------------------------------------------
    def run(self):
        self.connect_and_subscribe()

        while self.running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                    break
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.running = False
                        break
                    if ev.key == pygame.K_1:
                        self.owner = 1
                    if ev.key == pygame.K_2:
                        self.owner = 2
                    if ev.key == pygame.K_t:
                        idx = TOWER_TYPES.index(self.selected_tower_type)
                        self.selected_tower_type = TOWER_TYPES[(idx + 1) % len(TOWER_TYPES)]
                    if ev.key == pygame.K_g:
                        idx = TOWER_TYPES.index(self.selected_tower_type)
                        self.selected_tower_type = TOWER_TYPES[(idx - 1) % len(TOWER_TYPES)]
                    if ev.key == pygame.K_u:
                        mx, my = pygame.mouse.get_pos()
                        self.send_cmd(f"UPGRADE_TOWER {mx} {my}")
                    if ev.key == pygame.K_RETURN:
                        self.send_cmd("START")
                    if ev.key == pygame.K_r:
                        self.send_cmd("RESET")
                    if ev.key == pygame.K_TAB:
                        self.mode = "place_spawner" if self.mode == "buy_tower" else "buy_tower"

                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mx, my = ev.pos
                    if self.mode == "buy_tower":
                        self.send_cmd(
                            f"BUY_TOWER {self.owner} {mx} {my} {self.selected_tower_type}"
                        )
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

    # --------------------------------------------------
    # Drawing
    # --------------------------------------------------
    def draw(self):
        self.screen.fill((34, 36, 48))

        pygame.draw.line(self.screen, (60, 60, 80), (0, HEIGHT // 2), BASE_POS, 24)

        with self.state_lock:
            snap = copy.deepcopy(self.state)

        # obstacles
        for ob in snap.get("obstacles", []):
            try:
                r = pygame.Rect(int(ob["x"]), int(ob["y"]), int(ob["w"]), int(ob["h"]))
                pygame.draw.rect(self.screen, (90, 90, 100), r)
            except:
                continue

        # base
        pygame.draw.circle(self.screen, (60, 200, 120), BASE_POS, BASE_RADIUS)
        pygame.draw.circle(self.screen, (30, 160, 80), BASE_POS, BASE_RADIUS - 8)

        # spawners
        for s in snap.get("spawners", []):
            try:
                sx = int(s["x"])
                sy = int(s["y"])
                color = ORANGE if s["owner"] == 1 else RED
                pygame.draw.rect(self.screen, color, (sx - 12, sy - 12, 24, 24))
            except:
                continue

        # towers
        for t in snap.get("towers", []):
            try:
                tx, ty = int(t["x"]), int(t["y"])
                color = BLUE if t["owner"] == 1 else PURPLE
                pygame.draw.circle(self.screen, color, (tx, ty), 16)
                lvl = self.font.render(f"L{t.get('level',1)}", True, WHITE)
                self.screen.blit(lvl, (tx - lvl.get_width()//2, ty - lvl.get_height()//2))
            except:
                continue

        # enemies
        for e in snap.get("enemies", []):
            try:
                ex, ey = int(e["x"]), int(e["y"])
                etype = e.get("etype", "basic")
                color = (255, 120, 80)
                if etype == "fast":
                    color = (255, 200, 60)
                elif etype == "armored":
                    color = (200, 200, 220)
                pygame.draw.circle(self.screen, color, (ex, ey), 10)

                # hp bar
                w = 22
                h = 4
                x = ex - w // 2
                y = ey - 10 - 10
                pygame.draw.rect(self.screen, RED, (x, y, w, h))
                maxhp = 30
                if etype == "fast":
                    maxhp = 18
                if etype == "armored":
                    maxhp = 70
                hpw = max(0, int((e.get("hp", 0) / maxhp) * w))
                pygame.draw.rect(self.screen, GREEN, (x, y, hpw, h))
            except:
                continue

        self.draw_ui(snap)

    def draw_ui(self, snap):
        lines = [
            f"Mode: {'BUY TOWER' if self.mode=='buy_tower' else 'PLACE SPAWNER'} (TAB)",
            f"Owner: {self.owner} (1/2)",
            f"Tower type: {self.selected_tower_type} (T/G)",
            "Left-click place | U upgrade | ENTER start | R reset",
        ]
        for i, l in enumerate(lines):
            col = WHITE if i == 0 else GRAY
            r = self.font.render(l, True, col)
            self.screen.blit(r, (8, 8 + i * 18))

        money = snap.get("money", {"1": 0, "2": 0})
        mtxt = self.font.render(
            f"P1 Money: ${money.get('1',0)}   P2 Money: ${money.get('2',0)}",
            True, YELLOW)
        self.screen.blit(mtxt, (8, HEIGHT - 36))

        rt = int(snap.get("time_left", 0))
        rt_text = self.font.render(
            f"Time Left: {rt//60:02d}:{rt%60:02d}",
            True, GREEN)
        self.screen.blit(rt_text, (WIDTH//2 - rt_text.get_width()//2, 8))

        winner = snap.get("winner", "")
        if winner:
            msg = "TOWERS WIN!" if winner == "TOWERS" else "ENEMIES WIN!"
            col = GREEN if winner == "TOWERS" else RED
            h = self.bigfont.render(msg, True, col)
            self.screen.blit(h, (WIDTH//2 - h.get_width()//2, HEIGHT//2 - 20))


# --------------------------------------------------
# Entry
# --------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=9999)
    args = p.parse_args()

    client = NetClientGUI(args.host, args.port)
    client.run()


if __name__ == "__main__":
    main()
