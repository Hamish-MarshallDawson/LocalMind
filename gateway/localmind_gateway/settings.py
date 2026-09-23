"""Gateway settings, from environment variables (systemd reads them from an env file)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\s]+", value or "") if item.strip()]


@dataclass
class Settings:
    # Where LocalMind listens. The LAN address works even before Tailscale starts on the PC.
    pc_url: str = "https://localhost:7860"
    # The PC's wired network card, and this LAN's broadcast address, for Wake-on-LAN.
    pc_mac: str = ""
    wol_broadcast: str = "255.255.255.255"
    wol_port: int = 9
    # The PC's Tailscale name: lets the page say "PC is on, LocalMind starting" while it boots.
    pc_tailscale_name: str = ""
    # Shared with LocalMind (LOCALMIND_GATEWAY_TOKEN on both machines).
    token: str = ""
    # Tailscale logins allowed to use the gateway. `tailscale serve` tells us who is asking.
    allowed_users: list[str] = field(default_factory=list)
    data_dir: Path = Path("./gateway-data")
    host: str = "127.0.0.1"
    port: int = 8765
    # How long to wait for the PC to boot and LocalMind to load before giving up.
    wake_timeout: float = 420.0
    # LocalMind reports every minute; this long without one means the PC is off.
    offline_after: float = 150.0
    # A link to LocalMind's full interface, shown while the PC is on.
    pc_ui_url: str = ""

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            pc_url=env.get("LMG_PC_URL", defaults.pc_url).rstrip("/"),
            pc_mac=env.get("LMG_PC_MAC", ""),
            wol_broadcast=env.get("LMG_WOL_BROADCAST", defaults.wol_broadcast),
            wol_port=int(env.get("LMG_WOL_PORT", defaults.wol_port)),
            pc_tailscale_name=env.get("LMG_PC_TAILSCALE_NAME", ""),
            token=env.get("LOCALMIND_GATEWAY_TOKEN", "").strip(),
            allowed_users=[u.lower() for u in _list(env.get("LMG_ALLOWED_USERS", ""))],
            data_dir=Path(env.get("LMG_DATA_DIR", str(defaults.data_dir))),
            host=env.get("LMG_HOST", defaults.host),
            port=int(env.get("LMG_PORT", defaults.port)),
            wake_timeout=float(env.get("LMG_WAKE_TIMEOUT", defaults.wake_timeout)),
            offline_after=float(env.get("LMG_OFFLINE_AFTER", defaults.offline_after)),
            pc_ui_url=env.get("LMG_PC_UI_URL", "").rstrip("/"),
        )

    def problems(self) -> list[str]:
        issues = []
        if not self.token:
            issues.append("LOCALMIND_GATEWAY_TOKEN is not set, so the gateway can't talk to LocalMind.")
        if not self.pc_mac:
            issues.append("LMG_PC_MAC is not set, so the gateway can't wake the PC.")
        if not self.allowed_users and self.host not in ("127.0.0.1", "localhost", "::1"):
            issues.append("LMG_ALLOWED_USERS is empty while listening beyond this machine.")
        return issues
