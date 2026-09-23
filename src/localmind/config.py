from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ChatModelConfig(BaseModel):
    name: str = "Qwen/Qwen3-VL-8B-Instruct"
    quantization: str = "4bit"
    max_new_tokens: int = 4096
    device: str = "cuda"


class OCRModelConfig(BaseModel):
    name: str = "deepseek-ai/DeepSeek-OCR-2"
    quantization: str = "4bit"
    device: str = "cuda"


class RetrievalModelConfig(BaseModel):
    name: str = "vidore/colqwen2.5-v0.2"
    device: str = "cuda"


class EmbeddingModelConfig(BaseModel):
    name: str = "BAAI/bge-base-en-v1.5"
    device: str = "cpu"
    # Prepended to search queries only (not documents). Correct for bge-*-en-v1.5; set to ""
    # if you switch to an embedding model that doesn't use one.
    query_prefix: str = "Represent this sentence for searching relevant passages: "


class WhisperConfig(BaseModel):
    model_size: str = "medium"
    device: str = "cuda"
    compute_type: str = "float16"


class ModelsConfig(BaseModel):
    chat: ChatModelConfig = ChatModelConfig()
    ocr: OCRModelConfig = OCRModelConfig()
    retrieval: RetrievalModelConfig = RetrievalModelConfig()
    embedding: EmbeddingModelConfig = EmbeddingModelConfig()
    whisper: WhisperConfig = WhisperConfig()


class ChatModelOption(BaseModel):
    key: str
    label: str
    provider: Literal["local", "anthropic"] = "local"
    model: str
    family: str = ""
    thinking: Literal["none", "native", "variant", "always", "budget"] = "none"
    thinking_model: str | None = None
    vision: bool = False
    context_window: int = 32768
    max_output_tokens: int = 8192
    forced_tools: bool = True
    evidence_check: bool | None = None  # None: on for local models, off for Claude
    server_fallbacks: bool = False
    weights_gb: float = 0.0
    kv_cache: str | None = None
    attention_transient_kb: float = 16.0
    note: str = ""


def _default_chat_models() -> list[ChatModelOption]:
    return [
        ChatModelOption(
            key="qwen3-vl-8b", label="Qwen3-VL 8B", model="Qwen/Qwen3-VL-8B-Instruct", family="qwen",
            thinking="variant", thinking_model="Qwen/Qwen3-VL-8B-Thinking", vision=True,
            context_window=32768, weights_gb=6.0, kv_cache="fp8", attention_transient_kb=16.0, note="Thinking uses a separate checkpoint (~16 GB, downloaded on first use)",
        ),
        ChatModelOption(
            key="gemma-4-12b", label="Gemma 4 12B", model="google/gemma-4-12B-it", family="gemma4",
            thinking="native", vision=True, context_window=32768, weights_gb=7.3, kv_cache="bf16", attention_transient_kb=6.0,
        ),
        ChatModelOption(
            key="claude-opus-5", label="Claude Opus 5", provider="anthropic", model="claude-opus-5",
            thinking="native", vision=True, context_window=1_000_000, max_output_tokens=64000, server_fallbacks=True,
        ),
        ChatModelOption(
            key="claude-sonnet-5", label="Claude Sonnet 5", provider="anthropic", model="claude-sonnet-5",
            thinking="native", vision=True, context_window=1_000_000, max_output_tokens=64000,
        ),
        ChatModelOption(
            key="claude-haiku-4-5", label="Claude Haiku 4.5", provider="anthropic", model="claude-haiku-4-5",
            thinking="budget", vision=True, context_window=200_000, max_output_tokens=32000,
        ),
        ChatModelOption(
            key="claude-fable-5-1", label="Claude Fable 5.1", provider="anthropic", model="claude-fable-5-1",
            thinking="always", vision=True, context_window=1_000_000, max_output_tokens=64000,
            forced_tools=False, server_fallbacks=True, note="Requires usage credits; always thinks",
        ),
    ]


class ChatModelsConfig(BaseModel):
    default: str = "qwen3-vl-8b"
    default_kv_cache: str = "fp8"  # bf16 | fp8 | int4 | offload; each chat can change it
    options: list[ChatModelOption] = Field(default_factory=_default_chat_models)


class AgentConfig(BaseModel):
    max_tool_rounds: int = 20
    context_warning_threshold: float = 0.85
    show_thinking: bool = True
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    # Challenge an answer that used no tools at all (once per turn).
    require_evidence: bool = True
    # Context management for the running transcript.
    transcript_tool_chars: int = 4000
    keep_full_tool_results: int = 12
    # House style: the writing guide in the system prompt (British English, none of the usual
    # machine-writing tells), and American spellings in answers turned British (never in code,
    # URLs or LaTeX).
    style_guide: bool = True
    british_spelling: bool = True


class RAGConfig(BaseModel):
    db_path: str = "./data/lancedb"
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    hybrid_search: bool = True


class IngestConfig(BaseModel):
    supported_extensions: list[str] = [
        ".pdf", ".png", ".jpg", ".jpeg", ".webp",
        ".txt", ".md", ".tex",
        ".mp3", ".wav", ".flac", ".m4a", ".ogg",
    ]
    max_file_size_mb: int = 500
    docs_dir: str = "./data/documents"


class WebSearchConfig(BaseModel):
    enabled: bool = True
    max_results: int = 5
    region: str = "uk-en"
    max_retries: int = 3
    cache_ttl_seconds: int = 600


class WebFetchConfig(BaseModel):
    enabled: bool = True
    timeout_seconds: int = 20
    max_chars: int = 12000
    # An honest descriptive agent outperforms a spoofed browser string: Wikipedia and other
    # robot-policy sites serve it happily and reject pretend-Chrome. Cloudflare JS challenges
    # will still fail either way - those pages are simply skipped.
    user_agent: str = "LocalMind/0.1 (local research assistant; +https://github.com/localmind)"


class CodeExecutionConfig(BaseModel):
    enabled: bool = True
    timeout_seconds: int = 30


class FileOperationsConfig(BaseModel):
    enabled: bool = True
    allowed_dirs: list[str] = ["./data"]


class LatexConfig(BaseModel):
    enabled: bool = True
    # auto: latexmk / pdflatex if installed (MiKTeX, TeX Live), else Tectonic, downloaded once.
    engine: Literal["auto", "latexmk", "tectonic"] = "auto"
    timeout_seconds: int = 180


class ToolsConfig(BaseModel):
    web_search: WebSearchConfig = WebSearchConfig()
    web_fetch: WebFetchConfig = WebFetchConfig()
    code_execution: CodeExecutionConfig = CodeExecutionConfig()
    file_operations: FileOperationsConfig = FileOperationsConfig()
    latex: LatexConfig = LatexConfig()


class StorageConfig(BaseModel):
    conversations_db: str = "./data/conversations.db"


class VoiceConfig(BaseModel):
    # Listening reuses models.whisper (faster-whisper). This is the language you speak in;
    # "" lets Whisper guess, which is less reliable on short phrases.
    language: str = "en"
    # Speaking: Kokoro-82M, run on the CPU. Voices: af_heart, af_bella, am_michael, bf_emma,
    # bf_isabella, bm_george, bm_lewis and more (b = British English, a = American).
    tts_model: str = "onnx-community/Kokoro-82M-v1.0-ONNX"
    tts_file: str = "onnx/model.onnx"
    tts_voice: str = "af_heart"
    tts_speed: float = 1.0
    max_upload_mb: int = 25


class GatewayConfig(BaseModel):
    # The always-on gateway that wakes this PC and keeps its last status. Set the address and the
    # shared secret as environment variables (LOCALMIND_GATEWAY_URL, LOCALMIND_GATEWAY_TOKEN) so
    # neither your tailnet address nor the token ever lands in a config file. Empty: no reporting.
    url: str = ""
    report_interval_seconds: int = 60
    history_chats: int = 40  # how many recent chats the gateway keeps a copy of, for offline reading


class PowerConfig(BaseModel):
    # Shut the PC down after this long with no messages or actions. Only when LocalMind runs with
    # `serve --auto-shutdown` (the start-at-boot task does), so a copy you start by hand never
    # turns your PC off. 0 disables it.
    idle_shutdown_minutes: float = 10
    # Windows shows a countdown first; any message or action in that time cancels it.
    grace_seconds: int = 60
    # Someone using this PC's keyboard or mouse counts as activity.
    respect_local_input: bool = True
    # So does another program keeping the GPU this busy (a game, a training run).
    busy_gpu_percent: int = 30
    dry_run: bool = False  # log the shutdown instead of doing it


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"  # "0.0.0.0" (or `serve --lan`) to allow other devices on your network
    port: int = 7860
    username: str = "localmind"
    # Prefer the LOCALMIND_PASSWORD environment variable over writing a password in this file.
    password: str | None = None
    # The assistant can run Python and read files on this machine, so exposing it on the network
    # without a password is refused unless this is set deliberately.
    allow_lan_without_password: bool = False
    # Browsers only allow the microphone on https:// or localhost, so voice from a phone needs
    # HTTPS. "auto" turns it on whenever LocalMind is reachable from the network, with a
    # self-signed certificate made on first run (your browser will ask you to accept it once).
    https: Literal["auto", "on", "off"] = "auto"
    certificate_dir: str = "./data/tls"


class AppConfig(BaseSettings):
    models: ModelsConfig = ModelsConfig()
    chat_models: ChatModelsConfig = ChatModelsConfig()
    agent: AgentConfig = AgentConfig()
    rag: RAGConfig = RAGConfig()
    ingest: IngestConfig = IngestConfig()
    tools: ToolsConfig = ToolsConfig()
    storage: StorageConfig = StorageConfig()
    server: ServerConfig = ServerConfig()
    voice: VoiceConfig = VoiceConfig()
    gateway: GatewayConfig = GatewayConfig()
    power: PowerConfig = PowerConfig()


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    path = Path(path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f)
        return AppConfig(**data)
    return AppConfig()
