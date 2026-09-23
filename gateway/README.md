# LocalMind gateway

The always-on half of LocalMind. It runs on a small machine that never sleeps (a Proxmox host, a NUC, a Raspberry Pi) and
is the page you open on your phone or laptop, over Tailscale.

- **Your PC can be off.** Send a message and the gateway wakes the PC (Wake-on-LAN), waits for
  LocalMind to start, delivers the message with your model and options, and streams the answer back.
- **It remembers.** Recent chats and the PC's last status (model, GPU, and when and why it last
  shut down) stay readable while the PC is off.
- **Queue several tasks.** "Queue tasks" takes one set of instructions and several items (say five
  job descriptions); each becomes its own chat with a clean context, run one after another, even
  if the PC has to be woken first. Files they produce (compiled CVs) stay downloadable here.
- **Approve new abilities.** When the model asks for a skill or MCP server, you can approve or deny
  it from here.
- **The PC puts itself back to sleep** after 10 minutes without a message or action. Someone
  using the PC, another program using the GPU, or an answer still running all count as activity.

```
 phone / laptop ──tailscale──▶ gateway (always on)    ──Wake-on-LAN + HTTPS──▶ PC (LocalMind)
                                     ▲                                                  │
                                     └──────── status every minute + just before shutdown ┘
```

## Setup

### 1. Choose a shared token

Both machines use the same secret, `LOCALMIND_GATEWAY_TOKEN`. The installer below can make one.

### 2. Gateway, on the always-on machine

Copy this `gateway/` folder over and run the installer:

```bash
scp -r gateway root@YOUR-SERVER:/root/localmind-gateway
ssh -t root@YOUR-SERVER "cd /root/localmind-gateway && bash install.sh"
```

It asks for the PC's MAC address, LocalMind's address, and who may sign in (your Tailscale login),
then runs the gateway as a systemd service on `127.0.0.1:8765` and publishes it on the tailnet with
`tailscale serve`. Settings live in `/etc/localmind-gateway.env`.

For HTTPS (needed to install the page as an app on your phone), turn on **HTTPS Certificates**
under DNS in the Tailscale admin console, then run `bash install.sh` again.

### 3. LocalMind, on the PC

1. In `config.yaml`, set `gateway.url` to the address the installer printed.
2. From PowerShell **run as administrator**:

   ```powershell
   .\scripts\install-autostart.ps1
   ```

   This starts `localmind serve --lan --auto-shutdown` when Windows boots, before anyone signs in.
   It asks for `LOCALMIND_PASSWORD` and `LOCALMIND_GATEWAY_TOKEN` and saves them to your Windows
   account.
3. Check Wake-on-LAN once: shut the PC down, then press **Wake PC** in the gateway. If nothing
   happens, enable "Wake on LAN" / "Power on by PCI-E" in the BIOS and turn off "ErP"/"Deep sleep".
   (On this PC, the network card and Windows are already set up for it.)

## Settings (gateway)

| Variable | Meaning |
| --- | --- |
| `LMG_PC_URL` | LocalMind's address, e.g. `https://192.168.1.50:7860` |
| `LMG_PC_MAC` | The PC's wired network card, for Wake-on-LAN |
| `LMG_WOL_BROADCAST` | The LAN's broadcast address, e.g. `192.168.1.255` |
| `LMG_PC_TAILSCALE_NAME` | Lets the page say "PC is on, starting LocalMind" while it boots |
| `LMG_ALLOWED_USERS` | Tailscale logins allowed in (comma-separated) |
| `LOCALMIND_GATEWAY_TOKEN` | Shared with the PC |
| `LMG_WAKE_TIMEOUT` | Seconds to wait for the PC to boot (default 420) |

Idle shutdown is configured on the PC under `power:` in `config.yaml`.
