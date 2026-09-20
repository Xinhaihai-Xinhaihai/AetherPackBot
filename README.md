# AetherPackBot

Harbor + Brain. IM vendors dock at the harbor. Models sit in the brain. The agent only sees cargo.

HTTP/WS direct. No vendor SDKs.

## What it is

AetherPackBot is a local chatbot kernel with two docks:

- **Harbor** — message dock. Each IM is a berth. A live connection is a slip. HarborMaster picks a live slip. Incoming traffic becomes a Manifest.
- **Brain** — model dock. Cortex nodes talk OpenAI-compat / Ollama over one wire. The router picks a live node.

Dashboard: `http://127.0.0.1:7619`

## Quick start

Windows:

```bat
start_aetherpackbot.bat
```

Or:

```bash
python main.py
```

Config lives in `data/config/config.json`. Keep keys local. The copy in git has blank `api_key` fields.

## Harbor berths

Direct HTTP/WS dialects, no official bot SDK:

| Berth | Notes |
| --- | --- |
| `weixin_ilink` | Personal WeChat via ilink HTTP |
| `onebot` | OneBot v11. NapCat / SnowLuma / LLOneBot / Lagrange / go-cqhttp are the same dialect, different protocol sides |
| `qq_official` | QQ official bot HTTP |
| `telegram` | Bot API HTTP |
| `discord` | REST HTTP |
| `facebook` / `instagram` | Graph HTTP |
| `line` | Messaging API HTTP |
| `slack` | Web API HTTP |
| `kook` | KOOK HTTP |
| `lark` | Feishu HTTP |
| `dingtalk` | DingTalk HTTP |

Put accounts under `platforms` in `config.json`. Empty list means Harbor is up but nothing is moored.

## Brain

Providers in `config.json`:

- `openai_compat` — any OpenAI-style gate
- `ollama` — local lane

Lane is `cloud` or `local`. Brain registers cortex nodes at boot.

## Layout

```
aetherpackbot/
├── harbor/          # berth, slip, wire, HarborMaster
├── providers/       # cortex, dialects, Brain router
├── kernel/          # lifecycle
├── protocols/       # shared contracts
├── messaging/       # message pipeline
├── platforms/       # thin wrap over Harbor
├── agents/          # tool-calling agent
├── plugins/         # plugins
├── storage/         # config + sqlite
├── webapi/          # dashboard API on :7619
├── cli/             # boot
└── extensions/      # built-in commands
```

## Probe

Harbor reachability (needs live tokens / a local OneBot side):

```bat
scripts\run_harbor_probe.bat
```

## License

MIT
