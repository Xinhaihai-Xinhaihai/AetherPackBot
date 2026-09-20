# AetherPackBot

Harbor + Brain. IM vendors dock at the harbor. Models sit in the brain. The agent only sees cargo.

HTTP/WS Direct. No vendor SDKs.

Dashboard: `http://127.0.0.1:7619`

## What it is

- **Harbor** — message dock. Each IM is a berth. A live connection is a slip. Incoming traffic becomes a Manifest.
- **Brain** — model dock. Cortex nodes talk OpenAI-compat / Ollama. The router picks a live node.

## Windows local / 本机 Windows

Double-click `AetherPackBot.exe`. A Harbor window opens and loads the client page at `http://127.0.0.1:7619`. Closing the window stops the kernel.

```bat
desktop\build_client.bat
AetherPackBot.exe
```

Needs a local Python 3.10+ next to the repo, or `D:\1\AstrBot\backend\python\python.exe`, or `AETHERPACK_PYTHON`. The old `start_aetherpackbot.bat` is console-only.

## Linux cloud native / 云服务器原生（Linux）

Cloud native is **Linux only** (Ubuntu / Debian / RHEL / CentOS / Alma / Rocky). Do not use the Windows exe on a VPS.

Needs Python 3.10+, git, and a C toolchain for some wheels.

One-shot install:

```bash
git clone https://github.com/Xinhaihai-Xinhaihai/AetherPackBot.git /opt/aetherpackbot
cd /opt/aetherpackbot
sudo bash deploy/linux-native.sh --systemd
```

Without systemd:

```bash
sudo bash deploy/linux-native.sh
source .venv/bin/activate
python main.py
```

Manual path:

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip python3-dev git build-essential

# RHEL / CentOS / Alma / Rocky
sudo dnf install -y python3 python3-pip python3-devel git gcc gcc-c++ make

cd /opt/aetherpackbot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install .
python main.py
```

Open `http://SERVER_IP:7619`. Bind is `0.0.0.0:7619`. Open the port:

```bash
sudo ufw allow 7619/tcp
# or
sudo firewall-cmd --permanent --add-port=7619/tcp && sudo firewall-cmd --reload
```

systemd unit: `deploy/aetherpackbot.service`. Keys stay in `data/config/config.json` on the server. Personal WeChat / local OneBot protocol sides usually stay on a desktop; a Linux VPS only talks HTTP/WS to those gates.

## Docker / 云服务器容器（Linux）

Docker on a Linux host:

```bash
docker compose up -d --build
```

Or:

```bash
docker build -t aetherpackbot .
docker run -d --name aetherpackbot --restart unless-stopped \
  -p 7619:7619 -v "$PWD/data:/app/data" aetherpackbot
```

Dashboard: `http://SERVER_IP:7619`. Config and sqlite persist in `./data`.

## Harbor berths

| Berth | Notes |
| --- | --- |
| `weixin_ilink` | Personal WeChat via ilink HTTP |
| `onebot` | OneBot v11. NapCat / SnowLuma / LLOneBot / Lagrange / go-cqhttp |
| `qq_official` | QQ official bot HTTP |
| `telegram` / `discord` | Bot HTTP |
| `facebook` / `instagram` | Graph HTTP |
| `line` / `slack` / `kook` | HTTP |
| `lark` / `dingtalk` | Feishu / DingTalk HTTP |

Put accounts under `platforms` in `data/config/config.json`. Empty list means Harbor is up but nothing is moored. Git copy of config has blank `api_key`.

## Layout

```
aetherpackbot/   Harbor + Brain kernel
desktop/         Windows Harbor client (WebView2 window)
deploy/          Linux native script + systemd unit
Dockerfile       Linux container
```

## Probe

```bat
scripts\run_harbor_probe.bat
```

## License

MIT
