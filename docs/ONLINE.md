<!-- Online play: how to turn it on and connect. -->
# Play online (experimental)

This is the game's own Local Wireless mode, played over a network. You only open the game and use Local Wireless -> Create Room / Rooms List. No extra program is needed.

1. Host: open "Local Wireless" and create a room.
2. Guest: open "Local Wireless", find the room in the Rooms List, and join.
3. Host: when the join request appears ("wants to join!"), accept it.
4. Both players vote on a stage and pick their fighters.
5. The host starts the match with L+R.

No room to join? **F1 -> Online -> Find an opponent** asks the lobby for another player who is searching too (see
[Find an opponent](#find-an-opponent-f1)).

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
- Matchmaking needs lobby 1.3 or newer, the rollback "finding an opponent" of Smash (versus) lobby 1.4 or newer (`curl -s http://127.0.0.1:8080/status` on the server shows the version).
- Update a running server: copy the new `tools/net/ssbu_lobby.py` next to `deploy_lobby.sh` and run
  `sudo bash deploy_lobby.sh [port]` again (add `DOMAIN=...` if you used it), or just
  `sudo install -m 644 ssbu_lobby.py /opt/ssbu-lobby/ && sudo systemctl restart ssbu-lobby`. Players reconnect by themselves.

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

- Both players need the same game update (13.0.4 or 13.0.5) and the same mods. The game version and a hash of the
  loaded mods are part of the build id (e.g. `ssbu-recomp-ldn1-13.0.5`, or `ssbu-recomp-ldn1-13.0.5+m1a2b3c4d` with
  mods), shown in the log lines `[online] on` and `[online] mods`.
- Rooms of another version or another mod set are still listed (in the game's Rooms List and in F1 -> Online),
  but they cannot be joined: trying shows a box with the reason, for example
  "Different version: this room is 13.0.4, you have 13.0.5" or "MISSING: <mod names>".
- For lobby and LAN, the lobby code must match.

## Find an opponent (F1)

F1 -> **Online** shows how many players are online with your version and mods, and how many are searching.
Press **Find an opponent**: the lobby pairs you with another player of the same game version, the same mods and the
same lobby code who is searching too, and says who hosts. You can keep playing meanwhile: a box at the top of the
picture tells you when an opponent is found.

- **You host:** open Local Wireless -> Create Room (a room you already have open counts), and accept the other player's
  request when "wants to join!" appears.
- **They host:** open Local Wireless -> Rooms List: their room is shown first (the box tells you when it is open).
  Join it.

The menus are not driven for you: you create or join the room in the game as usual. **Cancel** stops the search (or
the match: the other player is told). A search with nobody to pair with ends after 2 minutes ("No opponent found");
a match ends when you are both in the room, or after 3 minutes if you never meet there. Players of an older version
of this project never search, so they are never matched; an older lobby server cannot match (F1 says so).

## Online rooms (F1)

F1 -> **Online** also lists every room of your lobby: host, game version, mods, players, and whether you can join.
Select a row to see why a room cannot be joined. Joining itself is done in the game: Local Wireless -> Rooms List.

Mods counted: the sub-folders of the characters folder (`SSBU_CHARACTERS`, a fighter's `fighter.json` name or the
folder name) and the DLLs of `SSBU_MODS`. Two copies of a mod match when their files have the same names and sizes.
`online_list_other = off` in `config\graphics.ini` keeps rooms of other builds out of the game's own list (they stay in F1).

An older lobby server lists only rooms of your own build (F1 says so); an older game keeps working as before and only
sees rooms of its own build.

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

1. **Switch it on:** in the game, **F1 -> Experimental -> Rollback netcode: ON**, then restart the game (Play SSBU.bat).
   Nothing extra to build: rollback runs on the normal game build (the game saves the fight by learning, at the start of
   each fight, which memory it writes). An older install's second copy for rollback (`ssbu_game_r1.dll`,
   `ssbu_native_rb.exe`, the folder `nro_bin_eh_o2r1`) is not used any more and can be deleted.
2. **Both players** need it on, the same game update (13.0.4 or 13.0.5) and the same version of this project.
3. **No code needed on the lobby:** with online play on its default (the public lobby) or any lobby server, just **open
   Smash (versus)**, pick your own fighter (player 2's panel can be anything) and start the match. The box "Online match:
   finding an opponent..." shows while the lobby looks for another player who does the same (same game version, same
   mods, same lobby code); once found, the two games agree on the stage, the rules and a shared random seed, and the match
   starts with rollback. The player who searched first is player 1. Esc or holding B stops waiting; nobody found in
   2 minutes = back to the character select. This needs lobby 1.4 or newer (an older lobby: the box says so; use a room code).
4. **Or with a room code** (section 2 above): one player uses `online_mode = host` and gives the code, the other
   `online_mode = join` with that code; both open Smash (versus) as above (no search: the code already connects the two).

**Local Wireless rooms do not use rollback.** A fight started from a Local Wireless room (the room's match and its waiting
stage) is always played with the game's own online netcode, whatever the two players' rollback setting: a short message
says so once. Two players with different rollback settings can therefore still play together in a room.

Input delay is chosen from the best measured round trip: 1 frame below about 117 ms, 2 frames from about 117 ms, 3 from 150 ms,
4 from about 184 ms (the rest of the trip is covered by rollback).

Limits today: rollbacks of 3 or more frames take a little longer than one frame (a short hitch at very high ping);
Windows only; tested between two games on one PC with simulated 150 ms ping and loss (0 desyncs), not yet much between
real players over the internet. Please report how it feels.


## Credit

Design adapted from SNO2207/WindowSmash, used with the author's permission.

Online play adapts parts of SNO2207/WindowSmash's network code (used with its author's agreement); the lobby protocol and the room code are ours.
