"""Pick device, precision and batch size for the machine this runs on.

Override any choice with environment variables (or in .env):
  LANDCLASS_DEVICE = cuda | cuda:1 | mps | cpu
  LANDCLASS_DTYPE  = fp32 | fp16 | bf16
  LANDCLASS_BATCH  = 16
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import dotenv_values

from .config import ENV_FILE


@dataclass
class Hardware:
    device: str
    dtype: str          # "fp32" | "fp16" | "bf16"
    batch_size: int
    name: str
    memory_gb: float | None

    def describe(self) -> str:
        mem = f", {self.memory_gb:.0f} GB" if self.memory_gb else ""
        return f"{self.name}{mem} · {self.device} · {self.dtype} · batch {self.batch_size}"


def _setting(key: str) -> str | None:
    return os.environ.get(key) or dotenv_values(ENV_FILE).get(key) or None


def _auto_dtype(name: str, capability: tuple[int, int]) -> str:
    major, _ = capability
    if major >= 8:
        return "bf16"   # Ampere and newer (RTX 30xx/40xx/50xx, A100, …)
    if major == 7 and "GTX" not in name.upper():
        return "fp16"   # Volta/Turing with tensor cores (RTX 20xx, T4, V100)
    return "fp32"       # GTX 16xx and older: fp16 is several times slower here


def _auto_batch(memory_gb: float, dtype: str) -> int:
    batch = 4 if memory_gb < 6 else 8 if memory_gb < 10 else 16 if memory_gb < 20 else 32
    if dtype != "fp32":
        batch *= 2      # half precision fits about twice as much
    return min(batch, 64)


def detect() -> Hardware:
    import torch

    device = _setting("LANDCLASS_DEVICE")
    if not device:
        if torch.cuda.is_available():
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    if device.startswith("cuda"):
        idx = torch.device(device).index or 0
        props = torch.cuda.get_device_properties(idx)
        name, memory_gb = props.name, props.total_memory / 2**30
        dtype = _auto_dtype(name, (props.major, props.minor))
        batch = _auto_batch(memory_gb, dtype)
    elif device == "mps":
        name, memory_gb, dtype, batch = "Apple GPU", None, "fp32", 8
    else:
        name, memory_gb, dtype, batch = f"CPU ({os.cpu_count()} threads)", None, "fp32", 8

    dtype = _setting("LANDCLASS_DTYPE") or dtype
    if dtype not in ("fp32", "fp16", "bf16"):
        raise ValueError(f"LANDCLASS_DTYPE must be fp32, fp16 or bf16, not {dtype!r}")
    batch = int(_setting("LANDCLASS_BATCH") or batch)
    return Hardware(device=device, dtype=dtype, batch_size=batch, name=name, memory_gb=memory_gb)


def torch_dtype(dtype: str):
    import torch

    return {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[dtype]


if __name__ == "__main__":
    print("Detected:", detect().describe())
