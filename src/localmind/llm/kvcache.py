"""KV cache options for local models: how attention keys/values are stored while generating.

The KV cache, not the model weights, is what limits context on a 16 GB card: Qwen3-VL-8B needs
~144 KB per token in bf16, so 32K tokens cost ~4.4 GB on top of the ~6 GB of weights.

Options:
  bf16     exact, the default.
  fp8      8-bit float per value with a per-token scale: ~2x the context, near-lossless.
  int4     4-bit, keys scaled per channel and values per token (the KIVI recipe): ~3.5x the
           context, some quality loss on exact recall.
  offload  exact, full precision, kept in system RAM and streamed to the GPU a layer at a time:
           context limited by RAM rather than VRAM, much slower generation.

Why not transformers' own QuantizedCache: every time its 128-token buffer fills it dequantizes the
whole cache and quantizes it again, so rounding error compounds (and chunked prefill makes it
flush every chunk). Here each block of tokens is quantized exactly once, from its original values.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
from transformers.cache_utils import DYNAMIC_LAYER_TYPE_MAPPING, Cache, DynamicCache, DynamicLayer, get_layer_types_and_kwargs

FP8 = torch.float8_e4m3fn
FP8_MAX = torch.finfo(FP8).max
INT4_GROUP = 32


@dataclass(frozen=True)
class KVCacheType:
    key: str
    label: str
    bytes_per_value: float  # storage cost per scalar in a K or V tensor, including scales
    description: str
    exact: bool
    slow: bool = False


# Measured on an RTX 5080 (16 GB) with Qwen3-VL-8B, needle-in-a-haystack recall at every size:
#   bf16     31K ctx 11.0 GB 12.2 tok/s | 62K out of memory
#   fp8      31K      9.0 GB  9.3 tok/s | 62K 11.9 GB 5.1 tok/s | 93K out of memory
#   int4     31K      8.1 GB  6.8 tok/s | 62K 10.0 GB 3.7 tok/s | 93K 12.0 GB 2.5 tok/s
#   offload  31K      7.0 GB  6.3 tok/s
# Gemma 4 12B needs little KV (40 of its 48 layers use a 1K sliding window): bf16 held 124K tokens
# in 10.9 GB at 5.3 tok/s, and fp8 saved almost nothing there.
KV_CACHE_TYPES: dict[str, KVCacheType] = {
    "bf16": KVCacheType("bf16", "bf16 · exact", 2.0, "full precision, fastest, least context", exact=True),
    "fp8": KVCacheType("fp8", "fp8 · ~2x context", 1.03, "8-bit, about twice the context, near-lossless, ~25% slower", exact=False),
    "int4": KVCacheType("int4", "int4 · ~3.5x context", 0.58, "4-bit, the most context on the GPU, slowest at long lengths", exact=False, slow=True),
    "offload": KVCacheType("offload", "offload · RAM", 0.0, "exact, kept in system RAM so it barely uses VRAM, about half speed", exact=True, slow=True),
}
DEFAULT_KV_CACHE = "bf16"


def kv_type(key: str | None) -> KVCacheType:
    return KV_CACHE_TYPES.get(key or DEFAULT_KV_CACHE, KV_CACHE_TYPES[DEFAULT_KV_CACHE])


# ------------------------------------------------------------------------------------ codecs
def fp8_compress(x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    scale = x.abs().amax(dim=-1, keepdim=True).float().clamp_min(1e-8) / FP8_MAX
    return (x.float() / scale).to(FP8), scale.to(x.dtype)


def fp8_decompress(q: torch.Tensor, scale: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    return q.to(dtype) * scale


def int4_compress(x: torch.Tensor, per_channel: bool) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, tuple]:
    """Asymmetric 4-bit. Keys: one scale per channel across the block's tokens (they carry outlier
    channels). Values: groups of INT4_GROUP along the head dimension for each token."""
    shape = x.shape  # [batch, heads, tokens, head_dim]
    xf = x.float()
    if per_channel:
        lo = xf.amin(dim=-2, keepdim=True)
        hi = xf.amax(dim=-2, keepdim=True)
        grouped = xf
    else:
        pad = (-shape[-1]) % INT4_GROUP
        if pad:
            xf = torch.nn.functional.pad(xf, (0, pad))
        grouped = xf.view(*shape[:-1], -1, INT4_GROUP)
        lo = grouped.amin(dim=-1, keepdim=True)
        hi = grouped.amax(dim=-1, keepdim=True)
    scale = ((hi - lo) / 15).clamp_min(1e-8)
    q = ((grouped - lo) / scale).round_().clamp_(0, 15).to(torch.uint8).flatten(start_dim=3)
    if q.shape[-1] % 2:
        q = torch.nn.functional.pad(q, (0, 1))
    packed = (q[..., 0::2] << 4) | q[..., 1::2]
    return packed, scale.to(x.dtype), lo.to(x.dtype), tuple(shape)


def int4_decompress(packed: torch.Tensor, scale: torch.Tensor, lo: torch.Tensor, shape: tuple, per_channel: bool, dtype: torch.dtype) -> torch.Tensor:
    q = torch.stack([packed >> 4, packed & 0x0F], dim=-1).flatten(start_dim=3)
    b, h, t, d = shape
    if per_channel:
        return (q[..., :d].view(b, h, t, d).to(dtype) * scale + lo).contiguous()
    groups = scale.shape[-2]
    x = q[..., : groups * INT4_GROUP].view(b, h, t, groups, INT4_GROUP).to(dtype) * scale + lo
    return x.flatten(start_dim=3)[..., :d].contiguous()


# ------------------------------------------------------------------------------------ layer
class CompressedLayer(DynamicLayer):
    """A full-attention cache layer storing old tokens compressed, recent tokens in full precision."""

    is_croppable = False
    FLUSH_AT = 256  # compress once the full-precision tail reaches this many tokens
    KEEP_RECENT = 32  # the most recent tokens stay exact; they matter most for the next token

    def __init__(self, codec: str):
        super().__init__()
        self.codec = codec
        self._blocks: list[tuple] = []
        self._compressed_len = 0

    def lazy_initialization(self, key_states: torch.Tensor, value_states: torch.Tensor) -> None:
        super().lazy_initialization(key_states, value_states)

    def _compress(self, keys: torch.Tensor, values: torch.Tensor) -> tuple:
        if self.codec == "fp8":
            return ("fp8", *fp8_compress(keys), *fp8_compress(values))
        return ("int4", int4_compress(keys, per_channel=True), int4_compress(values, per_channel=False))

    def _decompress(self, block: tuple) -> tuple[torch.Tensor, torch.Tensor]:
        if block[0] == "fp8":
            _, kq, ks, vq, vs = block
            return fp8_decompress(kq, ks, self.dtype), fp8_decompress(vq, vs, self.dtype)
        _, (kp, kscale, klo, kshape), (vp, vscale, vlo, vshape) = block
        return (
            int4_decompress(kp, kscale, klo, kshape, per_channel=True, dtype=self.dtype),
            int4_decompress(vp, vscale, vlo, vshape, per_channel=False, dtype=self.dtype),
        )

    def update(self, key_states: torch.Tensor, value_states: torch.Tensor, *args, **kwargs) -> tuple[torch.Tensor, torch.Tensor]:
        if not self.is_initialized:
            self.lazy_initialization(key_states, value_states)
        self.keys = torch.cat([self.keys, key_states], dim=-2)
        self.values = torch.cat([self.values, value_states], dim=-2)

        # Attention needs the exact new tokens plus everything before them, so assemble the full
        # sequence before compressing: compressing first would round the tokens being attended to.
        if self._blocks:
            parts = [self._decompress(block) for block in self._blocks]
            full_keys = torch.cat([p[0] for p in parts] + [self.keys], dim=-2)
            full_values = torch.cat([p[1] for p in parts] + [self.values], dim=-2)
        else:
            full_keys, full_values = self.keys, self.values

        tail = self.keys.shape[-2]
        if tail >= self.FLUSH_AT:
            cut = tail - self.KEEP_RECENT
            self._blocks.append(self._compress(self.keys[..., :cut, :], self.values[..., :cut, :]))
            self._compressed_len += cut
            self.keys = self.keys[..., cut:, :].contiguous()
            self.values = self.values[..., cut:, :].contiguous()
        return full_keys, full_values

    def get_seq_length(self) -> int:
        if not self.is_initialized:
            return 0
        return self._compressed_len + self.keys.shape[-2]

    def crop(self, tokens_to_remove: int) -> None:  # pragma: no cover - not used by plain generate()
        raise NotImplementedError("Compressed KV cache layers can't be cropped")


# ------------------------------------------------------------------------------------ factory
def make_cache(model_config, kind: str | None) -> Cache:
    """Build a generate()-compatible cache for `kind`. Sliding-window layers stay uncompressed:
    they are already capped at the window size."""
    kind = kv_type(kind).key
    text_config = model_config.get_text_config(decoder=True)
    if kind == "bf16":
        return DynamicCache(config=text_config)
    if kind == "offload":
        return DynamicCache(config=text_config, offloading=True)

    layer_types, layer_kwargs = get_layer_types_and_kwargs(text_config)
    layers = []
    for layer_type in layer_types:
        cls = DYNAMIC_LAYER_TYPE_MAPPING[layer_type]
        layers.append(CompressedLayer(kind) if cls is DynamicLayer else cls(**layer_kwargs))
    return Cache(layers=layers)


def layer_shapes(model_config) -> list[tuple[bool, int, int]]:
    """(is_sliding, kv_heads, head_dim) per decoder layer.

    Some models vary these per layer: Gemma 4 12B has 40 sliding layers with 8 KV heads x 256 dims
    but 8 global layers with a single KV head x 512 dims, so global attributes would be wrong.
    """
    text = model_config.get_text_config(decoder=True)
    layer_types, _ = get_layer_types_and_kwargs(text)
    per_layer = getattr(text, "per_layer_config", None)
    shapes = []
    for i, layer_type in enumerate(layer_types):
        source = per_layer[i] if per_layer is not None else text
        heads = getattr(source, "num_attention_heads", None) or text.num_attention_heads
        kv_heads = getattr(source, "num_key_value_heads", None) or heads
        head_dim = getattr(source, "head_dim", None) or text.hidden_size // heads
        shapes.append((DYNAMIC_LAYER_TYPE_MAPPING[layer_type] is not DynamicLayer, int(kv_heads), int(head_dim)))
    return shapes


def kv_bytes_per_token(model_config, kind: str | None, context: int) -> float:
    """Average KV bytes per token at `context` tokens, accounting for sliding-window layers."""
    text = model_config.get_text_config(decoder=True)
    _, layer_kwargs = get_layer_types_and_kwargs(text)
    per_value = kv_type(kind).bytes_per_value
    window = layer_kwargs.get("sliding_window") or getattr(text, "sliding_window", None) or context
    total = 0.0
    for sliding, kv_heads, head_dim in layer_shapes(model_config):
        tokens = min(context, window) if sliding else context
        # Sliding layers are never compressed; offloaded full layers cost no VRAM.
        bytes_here = 2.0 if sliding else per_value
        total += 2 * kv_heads * head_dim * bytes_here * tokens
    return total / max(context, 1)


def decode_transient_per_token(model_config) -> float:
    """Compressed layers re-expand one layer to bf16 (plus a concat copy) while decoding."""
    widest = max((kv * dim for sliding, kv, dim in layer_shapes(model_config) if not sliding), default=0)
    return 2 * 2 * widest * 2
