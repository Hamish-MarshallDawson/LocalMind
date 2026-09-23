# LocalMind

A private assistant that runs on your own PC, with a companion app you can reach from your phone.
Models, documents and chats stay on your machine; nothing is sent anywhere unless you choose to route to external models.

It does the ordinary things (chat, search your documents, search the web, run code) and a few
less ordinary ones: it speaks and listens, tailors a LaTeX CV to a job advert and compiles it,
queues a batch of jobs to run one after another, and — with a small always-on machine as a
gateway — wakes the PC when you message it from your phone, then lets it switch itself off again.

> Built for one desktop (an RTX 5080, 16 GB) and one person's workflow, so some defaults suit that
> setup. Everything in `config.yaml` can be changed.

## What it does

**Chat**
- Local models through transformers (Qwen3-VL 8B and Gemma 4 12B by default), or Claude models
  through the Anthropic API when you pick one.
- Answers stream while you scroll freely; switching chats doesn't stop an answer, it carries on in
  the background and is there when you come back.
- A live readout of VRAM, GPU use and how much context is left, with a warning near the limit.

**Knowledge base (RAG)**
- Index PDFs, images, text, Markdown, LaTeX and audio; audio is transcribed, scanned pages are
  read with OCR.
- Hybrid retrieval: vector search and keyword search fused with reciprocal rank fusion, in LanceDB.
- **Sections with visibility.** Each document belongs to a section. Shared sections (a general CV)
  are searchable from every chat; a private section (one employer's material) only from chats
  scoped to it, so one application can't see another's.

**Writing style**
- A house style built from Wikipedia's *Signs of AI writing*: no "delve", "tapestry", "showcases",
  no puffery, no "not just X but Y", no formulaic endings.
- British English, enforced deterministically on the way out (never inside code, URLs or LaTeX).

**Documents and LaTeX**
- The model can open the *original* of an indexed document (the real `.tex` of a CV, not retrieved
  fragments), write files into the chat's own folder, and compile LaTeX to PDF using the TeX
  already installed (MiKTeX/TeX Live), or Tectonic downloaded on demand and checked against its
  published checksum.
- Saving a file that came from an original reports exactly which lines changed, so the model
  describes what it really did rather than what it thinks it did.
- PDFs appear in the chat as downloads.

**Voice**
- Talk to it: faster-whisper transcribes, a Kokoro-82M model speaks the answer back sentence by
  sentence while it's still being written. Speech synthesis runs on the CPU, so it takes no VRAM.

**Task queue (Rough implementation)**
- One set of instructions plus several items (say five job adverts). Each becomes its own chat with
  a clean context, and they run strictly one after another.

**Skills and MCP (STILL BEING TESTED AND INTEGRATED)**
- Claude-style skills (`SKILL.md` folders) installed from a GitHub link; the model sees their names
  and descriptions, and loads the full instructions only when a task needs them.
- MCP servers (a command or a URL); their tools join the model's toolbox.
- The model can *ask* for a new skill or server with a reason, but **only you can approve it**, on
  the PC or from your phone.

**Phone access, and a PC that sleeps**
- An always-on gateway (a Proxmox host, a NUC, a Raspberry Pi) on your Tailscale network serves a
  mobile web app. It keeps your recent chats and the PC's last status, so it's useful even when the
  PC is off.
- Send a message while the PC is off: the gateway sends a Wake-on-LAN packet, waits for LocalMind,
  delivers the message and streams the answer back.
- The PC shuts itself down after ten idle minutes. Someone using the keyboard, another program
  using the GPU, a running answer or a waiting task all count as activity.
- See [gateway/README.md](gateway/README.md) for that half.

## How it fits together

```
 phone / laptop ──tailscale──▶ gateway (always on)  ──Wake-on-LAN──▶  PC
                                     │                                 │
                                     └────── HTTPS, shared token ──────┘
                                         status, chats, files

 PC:  Gradio web UI ─┐
      gateway API ───┼─▶ turn manager ─▶ agent ─▶ tools ─▶ local model (transformers)
      voice API ─────┘        │                    │              or Claude (API)
                        task queue          knowledge base (LanceDB), web, LaTeX,
                                            skills, MCP servers
```

Roughly: `src/localmind/agent` runs a turn (tool loop, context fitting, evidence check);
`llm` holds the model backends and the KV-cache work; `rag` the knowledge base and its sections;
`tools` the built-in tools; `extensions` skills, MCP and approvals; `ui` the Gradio app, the
background turn manager, the task queue and the APIs; `gateway/` is the separate always-on app.

## Requirements

- Windows (tested) or Linux, Python 3.10+.
- An NVIDIA GPU for local models. Cloud models work without one.
- Optional: MiKTeX or TeX Live for LaTeX, Tailscale and a small always-on machine for the gateway.

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e .
python -m localmind.cli serve    # http://127.0.0.1:7860
```

Index a few documents in the **Knowledge base** tab (or `localmind ingest <paths>`) and start
chatting. The first message downloads the model, which takes a while.

To reach it from other devices on your network:

```powershell
$env:LOCALMIND_PASSWORD = "choose-a-password"
python -m localmind.cli serve --lan
```

LAN mode requires a password (the assistant can run code and read files on that machine) and
serves HTTPS with a certificate made on first run, which the microphone needs.

## Configuration

Everything lives in `config.yaml`: models, the KV cache type, retrieval settings, tools, voice,
server and idle-shutdown behaviour. Secrets and machine-specific addresses come from the
environment instead, so they stay out of version control:

| Variable | What it's for |
| --- | --- |
| `LOCALMIND_PASSWORD` | Web UI password, required for `--lan` |
| `LOCALMIND_GATEWAY_URL` | Your gateway's address |
| `LOCALMIND_GATEWAY_TOKEN` | Shared secret between PC and gateway |
| `ANTHROPIC_API_KEY` | Only if you use the Claude models |

### Context and the KV cache

Context length is worked out from free VRAM, the model's weights and measured per-token costs,
rather than hardcoded. The cache type trades speed for length:

| Cache | What it means | Qwen3-VL 8B on 16 GB |
| --- | --- | --- |
| `bf16` | full precision, fastest | ~46K tokens |
| `fp8` | 8-bit, near-lossless, ~25% slower | ~67–75K |
| `int4` | 4-bit, most context, slowest at length | ~113K |
| `offload` | exact, kept in system RAM | ~70K |

## Tests

The project is developed against a suite of 214 tests (agent loop, KV-cache compression, retrieval
and section boundaries, writing style, background turns, the task queue, skills, MCP, the gateway
and the LaTeX tools). They aren't published in this repository yet.

## Privacy and safety

- Local models, documents and chats never leave the machine. Claude models are opt-in per chat, and
  the interface says so in the footer when one is selected.
- The gateway is reachable only inside your Tailscale network, and only by the logins you list;
  the PC and gateway authenticate to each other with a shared token.
- The model cannot install skills or MCP servers by itself: it can only ask, and you approve.
- `data/` (chats, documents, originals, certificates, skills) is git-ignored.

## Licence

MIT. See `pyproject.toml`.
