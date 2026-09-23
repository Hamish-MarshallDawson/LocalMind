"""Shutting the PC down when nobody has used LocalMind for a while.

The gateway wakes the PC for a message; this puts it back to sleep ten minutes after the last one,
so it isn't left running all day. It's cautious about what counts as "nobody": a running answer,
someone at the keyboard, or another program busy on the GPU all keep the PC on, and Windows shows
a one-minute countdown that any new message cancels.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from typing import Callable

from localmind.config import PowerConfig

logger = logging.getLogger(__name__)

CHECK_EVERY = 15.0  # seconds

# Usernames and session names can contain spaces, so read the row from the right: the session
# ID, state, idle time, then a logon time that starts with a digit.
_QUSER_ROW = re.compile(r"^.*\s(?P<id>\d+)\s+(?P<state>\S+)\s+(?P<idle>\S+)\s+(?P<logon>\d.*?)\s*$")


def parse_quser(output: str) -> list[float]:
    """Idle seconds of each *active* signed-in session in `quser` output.

    Idle time reads "none" or "." (in use), "5" (minutes), "1:05" (hours:minutes) or "2+03:04"
    (days+hours:minutes). Disconnected sessions don't count: nobody is sitting at them.
    """
    idles = []
    for line in output.splitlines()[1:]:
        match = _QUSER_ROW.match(line)
        if not match or match["state"].lower() not in ("active", "aktiv", "actif", "activo", "attivo"):
            continue
        idle = match["idle"]
        if idle in ("none", ".", "0"):
            idles.append(0.0)
            continue
        days, _, rest = idle.rpartition("+")
        hours, _, minutes = rest.rpartition(":")
        try:
            idles.append(((int(days or 0) * 24 + int(hours or 0)) * 60 + int(minutes)) * 60.0)
        except ValueError:
            continue
    return idles


def local_idle_seconds() -> float | None:
    """Seconds since someone last used this PC's keyboard or mouse; None if nobody's signed in."""
    if sys.platform != "win32":
        return None
    # LocalMind started at boot runs outside anyone's desktop session, where the usual Windows
    # call (GetLastInputInfo) only sees its own, empty session. `quser` reports every session.
    try:
        output = subprocess.run(["quser"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        output = ""
    if output.strip():
        idles = parse_quser(output)
        return min(idles) if idles else None
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:  # noqa: BLE001
        pass
    return None


def gpu_busy_percent() -> int | None:
    try:
        from localmind.metrics import gpu_stats

        stats = gpu_stats()
        return stats.util_percent if stats else None
    except Exception:  # noqa: BLE001
        return None


def system_shutdown_commands(grace: int, message: str) -> tuple[list[str], list[str]]:
    """(shut down after `grace` seconds, cancel a pending shutdown) for this OS."""
    if sys.platform == "win32":
        return ["shutdown", "/s", "/t", str(grace), "/c", message], ["shutdown", "/a"]
    return ["shutdown", "-h", f"+{max(1, round(grace / 60))}", message], ["shutdown", "-c"]


class PowerManager:
    def __init__(
        self,
        config: PowerConfig,
        *,
        enabled: bool,
        running_turns: Callable[[], set] = lambda: set(),
        before_shutdown: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        run: Callable[[list[str]], object] | None = None,
        clock: Callable[[], float] = time.time,
        local_idle: Callable[[], float | None] = local_idle_seconds,
        gpu_busy: Callable[[], int | None] = gpu_busy_percent,
    ):
        self.config = config
        self.enabled = enabled and config.idle_shutdown_minutes > 0
        self.running_turns = running_turns
        self.before_shutdown = before_shutdown
        self.on_change = on_change
        self.clock = clock
        self.local_idle = local_idle
        self.gpu_busy = gpu_busy
        self._run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, timeout=30))
        self._lock = threading.Lock()
        self.last_activity = clock()
        self.last_reason = "LocalMind started"
        self.hold_until = 0.0
        self.shutdown_at: float | None = None
        self.shutdown_reason = ""
        self._stop = threading.Event()

    @property
    def limit(self) -> float:
        return self.config.idle_shutdown_minutes * 60

    # ------------------------------------------------------------------ activity
    def touch(self, reason: str) -> None:
        """A message or action: restart the idle clock and call off any pending shutdown."""
        with self._lock:
            self.last_activity = self.clock()
            self.last_reason = reason
            pending = self.shutdown_at is not None
        if pending:
            self.cancel_shutdown(f"cancelled: {reason}")

    def keep_awake(self, minutes: float) -> None:
        with self._lock:
            self.hold_until = self.clock() + minutes * 60
        self.touch(f"kept awake for {minutes:g} minutes")

    def idle_seconds(self) -> float:
        return max(0.0, self.clock() - self.last_activity)

    def status(self) -> dict:
        now = self.clock()
        return {
            "auto_shutdown": self.enabled,
            "idle_limit_seconds": self.limit,
            "idle_seconds": round(self.idle_seconds()),
            "last_activity": self.last_activity,
            "last_activity_reason": self.last_reason,
            "keep_awake_until": self.hold_until if self.hold_until > now else None,
            "shutdown_at": self.shutdown_at,
            "shutdown_reason": self.shutdown_reason or None,
            "dry_run": self.config.dry_run,
        }

    # ------------------------------------------------------------------ checking
    def check(self) -> None:
        """Called every few seconds: note anything that counts as use, then shut down if idle."""
        if not self.enabled:
            return
        if self.shutdown_at is not None:
            # Counting down: someone sitting down at the PC calls it off.
            idle = self.local_idle() if self.config.respect_local_input else None
            if idle is not None and idle < CHECK_EVERY + 5:
                self.cancel_shutdown("cancelled: someone is using this PC")
            return
        now = self.clock()
        if self.running_turns():
            self._note("answering a message", now)
        if now < self.hold_until:
            self._note("kept awake from the gateway", now)
        if self.config.respect_local_input:
            idle = self.local_idle()
            if idle is not None and now - idle > self.last_activity:
                self._note("someone using this PC", now - idle)
        busy = self.gpu_busy()
        if busy is not None and busy >= self.config.busy_gpu_percent and not self.running_turns():
            self._note(f"another program using the GPU ({busy}%)", now)
        if self.idle_seconds() >= self.limit:
            minutes = self.config.idle_shutdown_minutes
            self.shutdown(f"No messages or activity for {minutes:g} minute{'s' if minutes != 1 else ''}")

    def _note(self, reason: str, when: float) -> None:
        with self._lock:
            if when > self.last_activity:
                self.last_activity = when
                self.last_reason = reason

    # ------------------------------------------------------------------ shutting down
    def shutdown(self, reason: str, grace: int | None = None) -> None:
        grace = self.config.grace_seconds if grace is None else grace
        with self._lock:
            if self.shutdown_at is not None:
                return
            self.shutdown_at = self.clock() + grace
            self.shutdown_reason = reason
        logger.warning("Shutting down in %ds: %s", grace, reason)
        if self.before_shutdown:
            try:
                self.before_shutdown(reason)  # the gateway's last word on what happened
            except Exception:  # noqa: BLE001 - never let reporting stop the shutdown
                logger.exception("Final status report failed")
        command, _ = system_shutdown_commands(grace, f"LocalMind: {reason}. Send a message to cancel.")
        if self.config.dry_run:
            logger.warning("Dry run, not running: %s", " ".join(command))
        else:
            self._run(command)
        self._changed()

    def cancel_shutdown(self, reason: str = "cancelled") -> None:
        with self._lock:
            if self.shutdown_at is None:
                return
            self.shutdown_at = None
            self.shutdown_reason = ""
            self.last_activity = self.clock()
            self.last_reason = reason
        logger.warning("Shutdown %s", reason)
        _, cancel = system_shutdown_commands(0, "")
        if not self.config.dry_run:
            self._run(cancel)
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                logger.exception("Power status report failed")

    # ------------------------------------------------------------------ background loop
    def start(self) -> None:
        if not self.enabled:
            logger.info("Idle shutdown is off (start with `serve --auto-shutdown` to enable it)")
            return
        logger.info("Idle shutdown: the PC turns off after %g minutes without activity", self.config.idle_shutdown_minutes)

        def loop():
            while not self._stop.wait(CHECK_EVERY):
                try:
                    self.check()
                except Exception:  # noqa: BLE001
                    logger.exception("Idle check failed")

        threading.Thread(target=loop, name="idle-shutdown", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
