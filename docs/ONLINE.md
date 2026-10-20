<!-- Online play: how to turn it on and connect. -->
# Play online (experimental)

This is the game's own Local Wireless mode, played over a network. You only open the game and use Local Wireless -> Create Room / Rooms List. No extra program is needed.

1. Host: open "Local Wireless" and create a room.
2. Guest: open "Local Wireless", find the room in the Rooms List, and join.
3. Host: when the join request appears ("wants to join!"), accept it.
4. Both players vote on a stage and pick their fighters.
5. The host starts the match with L+R.

Online play is experimental and ON by default: the game joins the project's public lobby
(`opensmash-lobby.duckdns.org:39500`) when it starts. To turn it off: F1 -> Experimental -> Online play: OFF
(or `online_mode = off` in `config\graphics.ini`).

**Your name:** F1 -> Experimental -> **Your name** (keyboard, or "Type with the controller"). It is the name the
game and the other players see (`player_name` in `config\graphics.ini`); empty = your Windows user name.
Used from the next start.

## The easy way: the F1 menu

Press **F1** (or the controller's Home button) -> **Experimental**. Online play is already ON; you can pick another mode:
**Lobby server** (recommended: the project's public lobby, `opensmash-lobby.duckdns.org:39500`, already filled in),
**Same network (LAN)**, **Host a room** (shows a ROOM CODE with a Copy button) or **Join with a code**.
Press **Restart the game now**, then use the game's own Local Wireless: Create Room / Rooms List.

The rest of this page is the same by hand (environment variables or graphics.ini keys).

## Turn it on

There are four ways to connect. Pick one and set it in one of two places:

- Environment variable `SSBU_ONLINE=...`
- A key in `config\graphics.ini`

Environment variables are read first. The graphics.ini keys are used when no variable is set.

### 1. Same network (LAN), no server

- `SSBU_ONLINE=lan`, or `online_mode = lan`.
- Rooms are found automatically. One of the games acts as the lobby.
- Uses UDP port 39501 (beacon) plus a random UDP port.

### 2. Internet without a server (host and join)

Host:

- `SSBU_ONLINE=host` or `SSBU_ONLINE=host:<port>`, or `online_mode = host`.
- The default port is UDP 39500 (`online_port` changes it).
- The log shows `ROOM CODE XXXXX-XXXXX`. Send this code to the other player.

Joiner:

- `SSBU_ONLINE=join:<code>`, or `online_mode = join` and `online_join = <code>`.

The host's router must let the port in:

- UPnP is tried automatically. Set `online_upnp = off` to disable it.
- Otherwise, forward UDP port 39500 to the host PC.
- If it still fails, the joiner's log prints "your code". The host puts that code in `online_peer`, and both restart. Both sides then open their NAT at the same time.
- If nothing works, use a lobby server (way 3).

### 3. Lobby server

- `SSBU_ONLINE=<host:port>`, or `online_server = <host:port>`.
- Players connect directly by UDP hole punching. If that fails, the lobby relays the traffic.
- `online_direct = off` (or `SSBU_ONLINE_DIRECT=0`): relay only. The lobby does not give anyone your address.

To run the lobby you need Python 3.8 or newer. It uses the standard library only, so there is nothing to install.

```
python tools/net/ssbu_lobby.py --bind 0.0.0.0 --port 39500 [--verbose]
```

- Open UDP port 39500 on that machine or on its router.
- Players do not need port forwarding.
- Self-test: `python tools/net/test_ssbu_lobby.py`
- On a Linux server (for example an Oracle Cloud Always Free Ubuntu VM): copy `tools/net/ssbu_lobby.py` and
  `tools/net/deploy_lobby.sh` to it and run `sudo bash deploy_lobby.sh [port]`. It installs a systemd service and opens
  the VM's firewall; open the same UDP port in the cloud's own firewall (Oracle: VCN Security List ingress rule).

### 4. Auto

- `SSBU_ONLINE=1`, or `online_mode = auto`.
- If `online_server` is set, it uses the lobby. After 5 seconds without an answer, it falls back to LAN.
- If `online_server` is not set, it uses LAN.

## Other settings

- `online_name` / `SSBU_ONLINE_NAME`: your name in the lobby log.
- `online_code` / `SSBU_ONLINE_CODE`: lobby code. Default: `public`.
- `online_direct = off` / `SSBU_ONLINE_DIRECT=0`: no direct connections (see way 3).
- `online_stun`: STUN server used to find your public address. Default `stun.l.google.com:19302`. Set `off` to disable.
- `SSBU_ONLINE_PORT`: local UDP port.
- `SSBU_ONLINE_LOG=0..3`: log level. Default 1.

## Requirements

- Both players need the same build and the same game update: a 13.0.4 player and a 13.0.5 player never see each
  other's rooms (the game version is part of the build id, e.g. `ssbu-recomp-ldn1-13.0.5`, shown in the log line `[online] on`).
- Both players need the same fighters and mods.
- For lobby and LAN, the lobby code must match.

## Status and limits

- Experimental.
- Tested with two game instances on one PC: lobby, LAN and host/join modes. Full matches ran with both players' inputs, and the fighters' states were identical frame by frame on both sides.
- NOT yet tested between two PCs, over the internet, against a real UPnP router, or with STUN.
- No encryption and no authentication. Play only with people you know.
- By default it uses the game's own delay-based netcode. **Rollback netcode** (experimental) is an option, see below.
- For now the room code is shown only in the log, on lines starting with `[online]`.
- On first start, Windows may ask to allow the game through the firewall. LAN and host modes need it.

## Rollback netcode (experimental)

Smooth fights at high ping: each game runs the match locally and only the players' inputs travel; a late input rolls the
game back a few frames and replays them, instead of slowing both players down.

1. **Build it once:** open `Install SSBU.bat`, tick **"Rollback netcode for online play"**, press **Install** (or
   **Resume**). It builds a second copy of the game with the extra bookkeeping rollback needs (`ssbu_game_r1.dll`,
   about as long as the first build) and puts `ssbu_native_rb.exe` beside it.
2. **Switch it on:** in the game, **F1 -> Experimental -> Rollback netcode: ON**, then restart the game (Play SSBU.bat).
3. **Both players** need it on, the same game update (13.0.4 or 13.0.5) and the same version of this project.
4. Play as usual through **Local Wireless**: each player picks only their own fighter; the two games agree on the stage,
   rules and a shared random seed before the match starts (a box "Online match" shows while they wait).

Limits today: rollbacks of 3 or more frames take a little longer than one frame (a short hitch at very high ping);
Windows only; tested between two games on one PC with simulated 150 ms ping and loss (0 desyncs), not yet much between
real players over the internet. Please report how it feels.


## Credit

Design adapted from SNO2207/WindowSmash, used with the author's permission.

Online play adapts parts of SNO2207/WindowSmash's network code (used with its author's agreement); the lobby protocol and the room code are ours.
