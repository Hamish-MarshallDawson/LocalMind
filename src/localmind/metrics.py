"""Live GPU readings for the status HUD."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_handle = None
_nvml_failed = False


@dataclass
class GpuStats:
    used_gb: float
    total_gb: float
    util_percent: int | None  # None when only torch is available (it can't read utilisation)
    name: str = ""

    @property
    def used_fraction(self) -> float:
        return self.used_gb / self.total_gb if self.total_gb else 0.0


def gpu_stats() -> GpuStats | None:
    """Whole-device readings, so VRAM includes other apps (browser, desktop) as well as LocalMind."""
    global _handle, _nvml_failed
    with _lock:
        if _handle is None and not _nvml_failed:
            try:
                import pynvml

                pynvml.nvmlInit()
                _handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception as e:  # noqa: BLE001
                logger.info("NVML unavailable (%s); falling back to torch for VRAM only", e)
                _nvml_failed = True
        if _handle is not None:
            try:
                import pynvml

                memory = pynvml.nvmlDeviceGetMemoryInfo(_handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(_handle)
                name = pynvml.nvmlDeviceGetName(_handle)
                return GpuStats(memory.used / 2**30, memory.total / 2**30, int(util.gpu), name if isinstance(name, str) else name.decode())
            except Exception as e:  # noqa: BLE001
                logger.debug("NVML read failed: %s", e)

    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return GpuStats((total - free) / 2**30, total / 2**30, None, torch.cuda.get_device_name(0))
    except Exception:  # noqa: BLE001
        pass
    return None
