# 2v2 Tower Defense (Host + Network Clients) - Python / Pygame

Overview

A lightweight 2v2 tower defense game with an authoritative host and optional networked clients. Two players place towers while two others place enemy spawners; the host runs the simulation and validates client actions.

Features

- Local and networked 2v2 tower defense gameplay.
- Multiple tower types, enemy types, money/cost/upgrade mechanics.
- Obstacles with A* pathfinding so enemies navigate around blocked tiles.
- Authoritative host that validates BUY/PLACE/UPGRADE commands; clients are thin controllers.
- Host broadcasts full game state as newline-delimited JSON snapshots (~10 Hz).
- A GUI network client (net_client_gui.py) can subscribe to the host and render live state with a shop UI.

Files

- main.py            - Host / authoritative game server (also renders locally)
- net_client_gui.py  - Networked GUI client (renders host state, sends buy/upgrade commands)
- net_client.py      - Simple text client for scripted placement/control

Requirements

- Python 3.8+
- pygame

Install

```bash
pip install pygame
```

Quick start — Local (no networking)

1. Run the host locally (no network):

```bash
python main.py
```

2. Use local controls to place towers/spawners and start the round.

Host with networking (remote clients)

1. Start the host in network mode (example port 9999):

```bash
python main.py --host --port 9999
```

2. Remote clients can connect:
- Use net_client.py for a text-based/scripted client.
- Use net_client_gui.py for a GUI client that renders live state and offers a shop UI.

Client commands (text protocol)

- SUBSCRIBE
- BUY_TOWER <owner> <x> <y> <type>
- PLACE_SPAWNER <owner> <x> <y>
- UPGRADE_TOWER <x> <y>
- START
- RESET
