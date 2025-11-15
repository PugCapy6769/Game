```markdown
# 2v2 Tower Defense (Host + Network Clients) - Python / Pygame

Overview
- Local + networked 2v2 tower defense.
- Two players place towers; two other players place enemy spawners.
- After setup, a timer runs (configurable). If any enemy reaches the base before the timer ends, enemies win; otherwise towers win.
- Features:
  - Money/cost/upgrade mechanics, multiple tower types, multiple enemy types.
  - Obstacles and A* pathfinding so enemies navigate around obstacles.
  - Authoritative host with client subscription: clients can BUY towers, PLACE spawners, UPGRADE towers, START and RESET.
  - Host broadcasts full game state as newline-delimited JSON snapshots (~10Hz).
  - A GUI network client (separate file) can subscribe and render the authoritative state and offer an in-game shop UI.

Files
- main.py            - Host / authoritative game (also renders locally)
- net_client_gui.py  - Networked GUI client (renders state, sends buy/upgrade commands)
- net_client.py      - Simple text client for scripted placement/control

Requirements
- Python 3.8+
- pygame
  - Install: `pip install pygame`

Quick start (local only)
1. Run host locally (no networking):
   ```
   python main.py
   ```
2. Use the local controls to place towers/spawners and start the round.

Host with network for remote clients
1. Start host with network enabled:
   ```
   python main.py --host --port 9999
   ```
2. Remote clients can connect:
   - Use `net_client.py` for a text-based client (scripted).
   - Use `net_client_gui.py` for a GUI client that renders live state and provides shop UI.

Client commands (text lines)
- SUBSCRIBE
- BUY_TOWER <owner> <x> <y> <type>
- PLACE_SPAWNER <owner> <x> <y>
- UPGRADE_TOWER <x> <y>
- START
- RESET

Notes
- The host is authoritative: it validates all buys/upgrades/placements. Clients are thin controllers.
- To make clients fully interactive with local prediction, we would need a richer protocol and conflict resolution; this project keeps authority on the host to avoid cheating.
- Default round time is 180 seconds (3 minutes) for quicker testing. Use `--round-time 600` for 10-minute matches.

If you'd like, I can:
- Add persistent maps and a map editor.
- Add per-player lobby and authentication.
- Implement rich client-side rendering (animations, sprites).
- Expand matchmaking and authoritative replay recording.

Enjoy!
```