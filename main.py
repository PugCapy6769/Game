#!/usr/bin/env python3
"""
Authoritative Host / Game Server + Local Renderer

- Runs the authoritative game and renders it locally with pygame.
- Accepts TCP clients:
  - Controller clients: send placement/buy/upgrade/start/reset commands (text lines).
  - Subscriber clients: send "SUBSCRIBE" and receive newline-delimited JSON state snapshots (~10Hz).
- Broadcasts authoritative state at ~10 updates/sec to subscribed clients.
- Validates BUY_TOWER and UPGRADE_TOWER server-side (money checks, placement rules).

Run:
    python main.py [--host] [--port 9999] [--round-time 180]

Controls (local):
    1/2/3/4: toggle placement modes for P1 towers, P2 towers, E1 spawners, E2 spawners
    T/G: cycle tower types when placing towers
    Left-click: place tower/spawner in placement mode (local placement uses BUY semantics)
    U: upgrade tower under mouse (sends upgrade request locally)
    ENTER: start round
    R: reset
    ESC: quit

Network protocol (text commands from clients):
    SUBSCRIBE
    BUY_TOWER <owner:int> <x:int> <y:int> <type:str>
    PLACE_SPAWNER <owner:int> <x:int> <y:int>
    UPGRADE_TOWER <x:int> <y:int>
    START
    RESET

Broadcasts: JSON objects per line with keys:
    phase, time_left, towers[], spawners[], enemies[], money{1,2}, obstacles[]
"""
import argparse
import json
import math
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

import pygame

# -------------------------------
# Configuration / Gameplay Vars
# -------------------------------
DEFAULT_ROUND_TIME = 180  # 3 minutes default; set to 600 for 10 minutes
MAX_TOWERS_PER_PLAYER = 8
MAX_SPAWNERS_PER_PLAYER = 4

# Tower defaults and types
TOWER_RADIUS = 16
TOWER_TYPES = {
    "basic": {"range": 140, "dmg": 12, "fire_rate": 0.8, "cost": 50, "upgrade_cost": 40},
    "sniper": {"range": 240, "dmg": 30, "fire_rate": 1.6, "cost": 90, "upgrade_cost": 80},
    "rapid": {"range": 100, "dmg": 6, "fire_rate": 0.25, "cost": 70, "upgrade_cost": 60},
}

# Enemy types
ENEMY_TYPES = {
    "basic": {"hp": 30, "speed": 60, "reward": 12, "color": (255, 120, 80)},
    "fast": {"hp": 18, "speed": 110, "reward": 10, "color": (255, 200, 60)},
    "armored": {"hp": 70, "speed": 45, "reward": 25, "color": (200, 200, 220)},
}

SPAWN_INTERVAL = 3.5

# Pathfinding grid
PATH_GRID_SIZE = 24
OBSTACLE_COUNT = 12

# Base
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

PHASE_SETUP = "SETUP"
PHASE_RUNNING = "RUNNING"
PHASE_GAMEOVER = "GAMEOVER"

# -------------------------------
# Utility
# -------------------------------
def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# -------------------------------
# Entities
# -------------------------------
@dataclass
class Enemy:
    pos: pygame.math.Vector2
    hp: float
    speed: float
    radius: int
    etype: str
    color: Tuple[int, int, int]
    path: List[Tuple[int, int]] = None
    path_index: int = 0

    def update(self, dt: float, pathfinder):
        if self.path and self.path_index < len(self.path):
            target = pygame.math.Vector2(self.path[self.path_index])
            dir_vec = (target - self.pos)
            if dir_vec.length_squared() < 1.0:
                self.path_index += 1
            else:
                dir_vec = dir_vec.normalize()
                self.pos += dir_vec * self.speed * dt
        else:
            target = pygame.math.Vector2(BASE_POS)
            direction = (target - self.pos)
            if direction.length() > 0:
                self.pos += direction.normalize() * self.speed * dt

    def to_dict(self):
        return {"x": float(self.pos.x), "y": float(self.pos.y), "hp": self.hp, "etype": self.etype}


@dataclass
class Tower:
    pos: Tuple[int, int]
    owner: int
    ttype: str = "basic"
    radius: int = TOWER_RADIUS
    range: int = 140
    dmg: float = 12
    fire_rate: float = 0.8
    cooldown: float = 0.0
    level: int = 1

    def __post_init__(self):
        spec = TOWER_TYPES[self.ttype]
        self.range = spec["range"]
        self.dmg = spec["dmg"]
        self.fire_rate = spec["fire_rate"]

    def upgrade(self):
        self.level += 1
        self.dmg *= 1.3
        self.range = int(self.range * 1.15)
        self.fire_rate = max(0.1, self.fire_rate * 0.9)

    def update(self, dt: float, enemies: List[Enemy]):
        if self.cooldown > 0:
            self.cooldown -= dt
        if self.cooldown <= 0:
            target = None
            min_d = 1e9
            for e in enemies:
                d = dist(self.pos, (e.pos.x, e.pos.y))
                if d <= self.range and d < min_d:
                    target = e
                    min_d = d
            if target:
                target.hp -= self.dmg
                self.cooldown = self.fire_rate

    def to_dict(self):
        return {"x": int(self.pos[0]), "y": int(self.pos[1]), "owner": self.owner, "ttype": self.ttype, "level": self.level}


@dataclass
class Spawner:
    pos: Tuple[int, int]
    owner: int
    spawn_timer: float
    spawn_interval: float = SPAWN_INTERVAL
    etype: str = "basic"

    def update(self, dt: float, enemies: List[Enemy], pathfinder):
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            roll = random.random()
            if roll < 0.65:
                etype = "basic"
            elif roll < 0.9:
                etype = "fast"
            else:
                etype = "armored"
            spec = ENEMY_TYPES[etype]
            epos = pygame.math.Vector2(self.pos[0] + random.uniform(-6, 6),
                                       self.pos[1] + random.uniform(-6, 6))
            e = Enemy(pos=epos, hp=spec["hp"], speed=spec["speed"], radius=10, etype=etype, color=spec["color"])
            path = pathfinder.find_path((int(epos.x), int(epos.y)), BASE_POS)
            if path:
                e.path = path
                e.path_index = 0
            enemies.append(e)
            self.spawn_timer = max(0.6, self.spawn_interval + random.uniform(-0.6, 0.6))

    def to_dict(self):
        return {"x": int(self.pos[0]), "y": int(self.pos[1]), "owner": self.owner}


# -------------------------------
# Pathfinding (A*)
# -------------------------------
class Pathfinder:
    def __init__(self, width: int, height: int, grid_size: int = PATH_GRID_SIZE):
        self.grid_size = grid_size
        self.cols = math.ceil(width / grid_size)
        self.rows = math.ceil(height / grid_size)
        self.grid = [[0 for _ in range(self.rows)] for __ in range(self.cols)]

    def world_to_cell(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        x, y = pos
        cx = max(0, min(self.cols - 1, x // self.grid_size))
        cy = max(0, min(self.rows - 1, y // self.grid_size))
        return cx, cy

    def cell_to_world_center(self, cell: Tuple[int, int]) -> Tuple[int, int]:
        cx, cy = cell
        return int(cx * self.grid_size + self.grid_size / 2), int(cy * self.grid_size + self.grid_size / 2)

    def set_obstacle_rect(self, rect: pygame.Rect):
        left = max(0, rect.left // self.grid_size)
        right = min(self.cols - 1, rect.right // self.grid_size)
        top = max(0, rect.top // self.grid_size)
        bottom = min(self.rows - 1, rect.bottom // self.grid_size)
        for cx in range(left, right + 1):
            for cy in range(top, bottom + 1):
                self.grid[cx][cy] = 1

    def clear(self):
        self.grid = [[0 for _ in range(self.rows)] for __ in range(self.cols)]

    def neighbors(self, node):
        x, y = node
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows and self.grid[nx][ny] == 0:
                yield nx, ny

    def heuristic(self, a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path(self, start_world: Tuple[int, int], goal_world: Tuple[int, int]) -> Optional[List[Tuple[int, int]]]:
        start = self.world_to_cell(start_world)
        goal = self.world_to_cell(goal_world)
        import heapq
        open_heap = [(0 + self.heuristic(start, goal), start)]
        came_from = {}
        gscore = {start: 0}
        fscore = {start: self.heuristic(start, goal)}
        while open_heap:
            _, current = heapq.heappop(open_heap)
            if current == goal:
                # reconstruct
                path = []
                cur = current
                while cur in came_from:
                    path.append(self.cell_to_world_center(cur))
                    cur = came_from[cur]
                path.append(self.cell_to_world_center(start))
                path.reverse()
                return path
            for nb in self.neighbors(current):
                tentative = gscore[current] + math.hypot(nb[0] - current[0], nb[1] - current[1])
                if tentative < gscore.get(nb, 1e9):
                    came_from[nb] = current
                    gscore[nb] = tentative
                    f = tentative + self.heuristic(nb, goal)
                    fscore[nb] = f
                    heapq.heappush(open_heap, (f, nb))
        return None


# -------------------------------
# Network Server
# -------------------------------
class ClientHandler(threading.Thread):
    def __init__(self, conn: socket.socket, addr, server):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.server = server
        self.subscribed = False
        self.running = True

    def run(self):
        try:
            self.conn.settimeout(0.5)
            buf = b""
            while self.running and self.server.running:
                try:
                    data = self.conn.recv(4096)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode("utf-8").strip()
                    except Exception:
                        continue
                    if not text:
                        continue
                    self.process_line(text)
        finally:
            self.close()

    def process_line(self, text: str):
        parts = text.split()
        if not parts:
            return
        cmd = parts[0].upper()
        try:
            if cmd == "SUBSCRIBE":
                # mark this client as a subscriber
                with self.server.lock:
                    self.subscribed = True
                    self.server.subscribers.append(self.conn)
                self.send_text("OK SUBSCRIBED\n")
            elif cmd == "BUY_TOWER" and len(parts) >= 5:
                owner = int(parts[1])
                x = int(parts[2]); y = int(parts[3]); ttype = parts[4]
                self.server.queue_command({"type": "buy_tower", "owner": owner, "pos": (x, y), "ttype": ttype})
            elif cmd == "PLACE_SPAWNER" and len(parts) >= 4:
                owner = int(parts[1]); x = int(parts[2]); y = int(parts[3])
                self.server.queue_command({"type": "place_spawner", "owner": owner, "pos": (x, y)})
            elif cmd == "UPGRADE_TOWER" and len(parts) >= 3:
                x = int(parts[1]); y = int(parts[2])
                self.server.queue_command({"type": "upgrade_tower", "pos": (x, y)})
            elif cmd == "START":
                self.server.queue_command({"type": "start"})
            elif cmd == "RESET":
                self.server.queue_command({"type": "reset"})
            else:
                self.send_text("ERR UNKNOWN_CMD\n")
        except Exception as e:
            self.send_text(f"ERR {e}\n")

    def send_text(self, txt: str):
        try:
            self.conn.sendall(txt.encode("utf-8"))
        except Exception:
            self.close()

    def close(self):
        if self.conn:
            try:
                with self.server.lock:
                    if self.conn in self.server.subscribers:
                        self.server.subscribers.remove(self.conn)
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass
        self.running = False


class NetworkServer(threading.Thread):
    def __init__(self, host: str, port: int, server):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True

    def run(self):
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.listen(8)
            self.sock.settimeout(1.0)
            print(f"[NET] Listening on {self.host}:{self.port}")
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                except socket.timeout:
                    continue
                print("[NET] Client connected", addr)
                handler = ClientHandler(conn, addr, self.server)
                handler.start()
                with self.server.lock:
                    self.server.client_threads.append(handler)
        finally:
            try:
                self.sock.close()
            except:
                pass

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except:
            pass


# -------------------------------
# Game Server (authoritative)
# -------------------------------
class GameServer:
    def __init__(self, round_time=DEFAULT_ROUND_TIME):
        pygame.init()
        pygame.display.set_caption("2v2 Tower Defense - Host")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 16)
        self.bigfont = pygame.font.SysFont("consolas", 32)

        # game state
        self.phase = PHASE_SETUP
        self.towers: List[Tower] = []
        self.spawners: List[Spawner] = []
        self.enemies: List[Enemy] = []
        self.obstacles: List[pygame.Rect] = []
        self.time_left = round_time
        self.placement_mode = 0
        self.tower_counts = {1: 0, 2: 0}
        self.spawner_counts = {1: 0, 2: 0}
        self.winner = None
        self.gameover_timer = 0.0
        self.money = {1: 200, 2: 200}

        self.pathfinder = Pathfinder(WIDTH, HEIGHT, PATH_GRID_SIZE)
        self.generate_obstacles()

        # networking
        self.subscribers: List[socket.socket] = []
        self.client_threads: List[ClientHandler] = []
        self.net_thread: Optional[NetworkServer] = None

        # thread-safe queue of commands from clients
        self.lock = threading.Lock()
        self.cmd_queue: List[Dict] = []
        self.running = True

    def generate_obstacles(self):
        self.pathfinder.clear()
        self.obstacles = []
        margin = 120
        tries = 0
        while len(self.obstacles) < OBSTACLE_COUNT and tries < OBSTACLE_COUNT * 4:
            tries += 1
            w = random.randint(40, 140)
            h = random.randint(24, 80)
            x = random.randint(margin, WIDTH - margin - w)
            y = random.randint(40, HEIGHT - 40 - h)
            r = pygame.Rect(x, y, w, h)
            if r.colliderect(pygame.Rect(BASE_POS[0] - BASE_RADIUS - 40, BASE_POS[1] - BASE_RADIUS - 40, (BASE_RADIUS + 40) * 2, (BASE_RADIUS + 40) * 2)):
                continue
            self.obstacles.append(r)
            self.pathfinder.set_obstacle_rect(r)

    def queue_command(self, cmd: Dict):
        with self.lock:
            self.cmd_queue.append(cmd)

    def process_commands(self):
        with self.lock:
            queue = self.cmd_queue[:]
            self.cmd_queue = []
        for cmd in queue:
            t = cmd.get("type")
            if t == "buy_tower":
                owner = cmd["owner"]; pos = cmd["pos"]; ttype = cmd.get("ttype", "basic")
                self._attempt_buy_tower(owner, pos, ttype)
            elif t == "place_spawner":
                owner = cmd["owner"]; pos = cmd["pos"]
                self._attempt_place_spawner(owner, pos)
            elif t == "upgrade_tower":
                pos = cmd["pos"]
                self._attempt_upgrade_tower_at(pos)
            elif t == "start":
                self.start_round()
            elif t == "reset":
                self.reset()

    # Attempt functions validate and mutate authoritative state
    def _attempt_buy_tower(self, owner: int, pos: Tuple[int, int], ttype: str):
        mx, my = pos
        if dist((mx, my), BASE_POS) < BASE_RADIUS + 40:
            return
        if self.tower_counts.get(owner, 0) >= MAX_TOWERS_PER_PLAYER:
            return
        cost = TOWER_TYPES.get(ttype, TOWER_TYPES["basic"])["cost"]
        if self.money.get(owner, 0) < cost:
            return
        for t in self.towers:
            if dist(t.pos, (mx, my)) < TOWER_RADIUS * 2:
                return
        t = Tower(pos=(mx, my), owner=owner, ttype=ttype)
        self.towers.append(t)
        self.tower_counts[owner] += 1
        self.money[owner] -= cost
        print(f"[HOST] BUY_TOWER owner={owner} pos={pos} type={ttype}")

    def _attempt_place_spawner(self, owner: int, pos: Tuple[int, int]):
        mx, my = pos
        if dist((mx, my), BASE_POS) < BASE_RADIUS + 40:
            return
        if self.spawner_counts.get(owner, 0) >= MAX_SPAWNERS_PER_PLAYER:
            return
        for s in self.spawners:
            if dist(s.pos, (mx, my)) < 28:
                return
        s = Spawner(pos=(mx, my), owner=owner, spawn_timer=random.uniform(0, 2))
        self.spawners.append(s)
        self.spawner_counts[owner] += 1
        print(f"[HOST] PLACE_SPAWNER owner={owner} pos={pos}")

    def _attempt_upgrade_tower_at(self, pos: Tuple[int, int]):
        mx, my = pos
        # find nearest tower within range
        nearest = None
        nd = 1e9
        for t in self.towers:
            d = dist(t.pos, (mx, my))
            if d < nd and d <= t.radius + 16:
                nearest = t; nd = d
        if not nearest:
            return
        cost = TOWER_TYPES.get(nearest.ttype, TOWER_TYPES["basic"])["upgrade_cost"] * nearest.level
        if self.money.get(nearest.owner, 0) < cost:
            return
        self.money[nearest.owner] -= cost
        nearest.upgrade()
        print(f"[HOST] UPGRADED tower at {nearest.pos} owner={nearest.owner} new_level={nearest.level}")

    def start_network(self, host_ip: str, host_port: int):
        self.net_thread = NetworkServer(host_ip, host_port, self)
        self.net_thread.start()

    def start_round(self):
        if self.phase != PHASE_SETUP:
            return
        if len(self.spawners) == 0:
            s1 = Spawner(pos=(40, HEIGHT // 3), owner=1, spawn_timer=0.5)
            s2 = Spawner(pos=(40, HEIGHT * 2 // 3), owner=2, spawn_timer=1.0)
            self.spawners.extend([s1, s2])
        self.phase = PHASE_RUNNING
        self.time_left = max(1, self.time_left)
        print("[HOST] Round started")

    def reset(self):
        rt = self.time_left
        with self.lock:
            self.__init__(round_time=rt)

    def update(self, dt: float):
        # first process queued client commands
        self.process_commands()

        if self.phase == PHASE_RUNNING:
            for s in self.spawners:
                s.update(dt, self.enemies, self.pathfinder)
            for e in self.enemies:
                e.update(dt, self.pathfinder)
            # reward money for killed enemies
            survivors = []
            for e in self.enemies:
                if e.hp <= 0:
                    reward = ENEMY_TYPES[e.etype]["reward"]
                    self.money[1] += reward // 2
                    self.money[2] += reward - (reward // 2)
                else:
                    survivors.append(e)
            self.enemies = survivors
            for t in self.towers:
                t.update(dt, self.enemies)
            # check infiltration
            for e in self.enemies:
                if dist((e.pos.x, e.pos.y), BASE_POS) <= BASE_RADIUS:
                    self.phase = PHASE_GAMEOVER
                    self.winner = "ENEMIES"
                    self.gameover_timer = 0.0
                    print("[HOST] ENEMIES WIN - infiltration")
                    return
            self.time_left -= dt
            if self.time_left <= 0:
                self.phase = PHASE_GAMEOVER
                self.winner = "TOWERS"
                self.gameover_timer = 0.0
                print("[HOST] TOWERS WIN - timer elapsed")
        elif self.phase == PHASE_GAMEOVER:
            self.gameover_timer += dt

    # Build a JSON-serializable snapshot of state
    def build_snapshot(self):
        with self.lock:
            snapshot = {
                "phase": self.phase,
                "time_left": float(self.time_left),
                "towers": [t.to_dict() for t in self.towers],
                "spawners": [s.to_dict() for s in self.spawners],
                "enemies": [e.to_dict() for e in self.enemies],
                "money": {"1": int(self.money[1]), "2": int(self.money[2])},
                "obstacles": [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in self.obstacles],
                "winner": self.winner or ""
            }
            return snapshot

    def broadcast_loop(self, hz=10):
        interval = 1.0 / hz
        while self.running:
            snap = self.build_snapshot()
            data = (json.dumps(snap) + "\n").encode("utf-8")
            with self.lock:
                subs = list(self.subscribers)
            for s in subs:
                try:
                    s.sendall(data)
                except Exception:
                    with self.lock:
                        if s in self.subscribers:
                            try:
                                self.subscribers.remove(s)
                                s.close()
                            except:
                                pass
            time.sleep(interval)

    def run(self, host_mode=False, host_ip="0.0.0.0", host_port=9999):
        # start network server if requested
        if host_mode:
            self.start_network(host_ip, host_port)
        # start broadcaster thread
        broadcaster = threading.Thread(target=self.broadcast_loop, daemon=True)
        broadcaster.start()

        last_time = time.time()
        try:
            while True:
                now = time.time()
                dt = now - last_time
                last_time = now
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        raise KeyboardInterrupt()
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            raise KeyboardInterrupt()
                        if event.key == pygame.K_r:
                            self.reset()
                        if event.key == pygame.K_1:
                            self.placement_mode = 1
                        if event.key == pygame.K_2:
                            self.placement_mode = 2
                        if event.key == pygame.K_3:
                            self.placement_mode = 3
                        if event.key == pygame.K_4:
                            self.placement_mode = 4
                        if event.key == pygame.K_RETURN:
                            if self.phase == PHASE_SETUP:
                                self.start_round()
                            elif self.phase == PHASE_GAMEOVER:
                                self.reset()
                        if event.key == pygame.K_u:
                            mx, my = pygame.mouse.get_pos()
                            self._attempt_upgrade_tower_at((mx, my))
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        mx, my = event.pos
                        if self.placement_mode in (1, 2):
                            # local buy (owner = placement_mode)
                            # default to basic type unless T/G logic present locally
                            # For local convenience, buy "basic"
                            self.queue_command({"type": "buy_tower", "owner": self.placement_mode, "pos": (mx, my), "ttype": "basic"})
                        elif self.placement_mode in (3, 4):
                            self.queue_command({"type": "place_spawner", "owner": self.placement_mode - 2, "pos": (mx, my)})

                # update game
                self.update(dt)
                # draw
                self.draw()
                pygame.display.flip()
                self.clock.tick(60)
        except KeyboardInterrupt:
            print("Shutting down.")
        finally:
            self.running = False
            if self.net_thread:
                self.net_thread.stop()
            with self.lock:
                for t in self.client_threads:
                    try:
                        t.close()
                    except:
                        pass
                for s in self.subscribers:
                    try:
                        s.close()
                    except:
                        pass
            pygame.quit()

    def draw(self):
        self.screen.fill((34, 36, 48))
        pygame.draw.line(self.screen, (60, 60, 80), (0, HEIGHT // 2), BASE_POS, 24)
        for r in self.obstacles:
            pygame.draw.rect(self.screen, (90, 90, 100), r)
        pygame.draw.circle(self.screen, (60, 200, 120), BASE_POS, BASE_RADIUS)
        pygame.draw.circle(self.screen, (30, 160, 80), BASE_POS, BASE_RADIUS - 8)
        base_text = self.font.render("BASE", True, BLACK)
        self.screen.blit(base_text, (BASE_POS[0] - base_text.get_width() // 2, BASE_POS[1] - 10))
        for s in self.spawners:
            color = ORANGE if s.owner == 1 else RED
            pygame.draw.rect(self.screen, color, (s.pos[0] - 12, s.pos[1] - 12, 24, 24))
        for t in self.towers:
            color = BLUE if t.owner == 1 else PURPLE
            pygame.draw.circle(self.screen, color, (int(t.pos[0]), int(t.pos[1])), t.radius)
            lvl = self.font.render(f"L{t.level}", True, WHITE)
            self.screen.blit(lvl, (t.pos[0] - lvl.get_width() // 2, t.pos[1] - lvl.get_height() // 2))
        for e in self.enemies:
            pygame.draw.circle(self.screen, e.color, (int(e.pos.x), int(e.pos.y)), e.radius)
            w = 22; h = 4
            x = int(e.pos.x - w / 2); y = int(e.pos.y - e.radius - 10)
            pygame.draw.rect(self.screen, RED, (x, y, w, h))
            hp_w = max(0, int((e.hp / ENEMY_TYPES[e.etype]["hp"]) * w))
            pygame.draw.rect(self.screen, GREEN, (x, y, hp_w, h))
        # HUD
        self.draw_hud()

    def draw_hud(self):
        lines = [
            "Controls:",
            "1 - Tower P1 placement | 2 - Tower P2 placement",
            "3 - Enemy E1 spawner placement | 4 - Enemy E2 spawner placement",
            "Left-click to place (local BUY). U - upgrade tower under mouse",
            "ENTER - Start | R - Reset | ESC - Quit",
        ]
        for i, l in enumerate(lines):
            r = self.font.render(l, True, WHITE if i == 0 else GRAY)
            self.screen.blit(r, (8, 8 + i * 18))
        txt = self.font.render(f"Towers: P1={self.tower_counts[1]} P2={self.tower_counts[2]}  Spawners: E1={self.spawner_counts[1]} E2={self.spawner_counts[2]}  Enemies={len(self.enemies)}", True, WHITE)
        self.screen.blit(txt, (8, HEIGHT - 60))
        moneytxt = self.font.render(f"P1 Money: ${self.money[1]}   P2 Money: ${self.money[2]}", True, YELLOW)
        self.screen.blit(moneytxt, (8, HEIGHT - 36))
        rt_text = self.font.render(f"Time Left: {format_time(self.time_left)}", True, GREEN)
        self.screen.blit(rt_text, (WIDTH // 2 - rt_text.get_width() // 2, 8))


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", action="store_true", help="Run network host (accept remote clients)")
    parser.add_argument("--port", type=int, default=9999, help="Port for network host")
    parser.add_argument("--round-time", type=int, default=DEFAULT_ROUND_TIME, help="Round time in seconds")
    args = parser.parse_args()

    server = GameServer(round_time=args.round_time)
    try:
        server.run(host_mode=args.host, host_ip="0.0.0.0", host_port=args.port)
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        server.running = False
        if server.net_thread:
            server.net_thread.stop()


if __name__ == "__main__":
    main()