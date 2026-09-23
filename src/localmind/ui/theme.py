"""LocalMind visual theme.

Palette
  Deep Space Blue  #12263A   sidebar, text, dark surfaces
  Strong Cyan      #06BCC1   accent: send button, active states, tool rails
  Ash Grey         #C5D8D1   borders, muted text on dark
  Parchment        #F4EDEA   page background (light), text (dark)
  Soft Apricot     #F4D1AE   user message bubbles

Contrast notes (WCAG): cyan on parchment is only ~2:1, so light-mode links and accent text use
a deepened cyan (#026A6E, ~5.6:1). Buttons put navy on cyan (~6.6:1) rather than white (~2.3:1).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import gradio as gr


def _icon(body: str) -> str:
    """A Lucide-style stroke icon as a CSS mask, so it takes the button's text colour."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
        f"stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>{body}</svg>"
    )
    return f'url("data:image/svg+xml,{quote(svg)}")'


ICON_PLUS = _icon("<path d='M12 5v14M5 12h14'/>")
ICON_CHAT = _icon("<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/>")
ICON_BOOK = _icon("<path d='M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z'/><path d='M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z'/>")
ICON_SEARCH = _icon("<circle cx='11' cy='11' r='8'/><path d='m21 21-4.3-4.3'/>")
ICON_GLOBE = _icon("<circle cx='12' cy='12' r='10'/><path d='M2 12h20'/><path d='M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'/>")
ICON_DOWNLOAD = _icon("<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><path d='m7 10 5 5 5-5'/><path d='M12 15V3'/>")
ICON_MIC = _icon("<path d='M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z'/><path d='M19 10v2a7 7 0 0 1-14 0v-2'/><path d='M12 19v3'/>")
ICON_TASKS = _icon("<path d='M9 6h11M9 12h11M9 18h11'/><path d='m3 6 1.5 1.5L7 5M3 12l1.5 1.5L7 11M3 18l1.5 1.5L7 17'/>")
ICON_TOOLS = _icon("<path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z'/>")
ICON_SPARK = _icon("<path d='M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z'/>")

NAVY = "#12263A"
CYAN = "#06BCC1"
ASH = "#C5D8D1"
PARCHMENT = "#F4EDEA"
APRICOT = "#F4D1AE"

CYAN_DEEP = "#026A6E"
NAVY_DEEP = "#0A1826"
NAVY_SURFACE = "#162C42"
NAVY_LINE = "#24425C"

_cyan = gr.themes.Color(
    name="lm_cyan",
    c50="#E6FAFA", c100="#C2F2F3", c200="#8FE6E8", c300="#52D6D9", c400="#22C7CB",
    c500=CYAN, c600="#059DA1", c700=CYAN_DEEP, c800="#045457", c900="#033E40", c950="#022A2C",
)
_navy = gr.themes.Color(
    name="lm_navy",
    c50="#F4EDEA", c100="#E4E9E7", c200=ASH, c300="#9FB3B6", c400="#6F8795",
    c500="#4A6275", c600="#2F4A61", c700=NAVY_LINE, c800=NAVY_SURFACE, c900=NAVY, c950=NAVY_DEEP,
)

THEME = gr.themes.Base(
    primary_hue=_cyan,
    secondary_hue=_navy,
    neutral_hue=_navy,
    radius_size=gr.themes.sizes.radius_lg,
    # Plain strings, not gr.themes.GoogleFont: Gradio 6.27's launch() compares theme fonts
    # against built-in themes and crashes when a GoogleFont meets a str. The webfonts are
    # loaded by an @import in CSS instead, and fall back to system fonts offline.
    font=["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
    font_mono=["JetBrains Mono", "ui-monospace", "Consolas", "monospace"],
).set(
    body_background_fill=PARCHMENT,
    body_background_fill_dark="#0F2031",
    body_text_color=NAVY,
    body_text_color_dark=PARCHMENT,
    body_text_color_subdued="#4F6272",
    body_text_color_subdued_dark="#9FB3B6",
    background_fill_primary="#FBF8F6",
    background_fill_primary_dark=NAVY_SURFACE,
    background_fill_secondary="#EFE6E1",
    background_fill_secondary_dark=NAVY,
    block_background_fill="#FBF8F6",
    block_background_fill_dark=NAVY_SURFACE,
    block_border_color="#E2D8D2",
    block_border_color_dark=NAVY_LINE,
    block_border_width="1px",
    block_shadow="none",
    block_label_text_color="#4F6272",
    block_label_text_color_dark="#9FB3B6",
    border_color_primary="#E2D8D2",
    border_color_primary_dark=NAVY_LINE,
    color_accent=CYAN,
    color_accent_soft="#DDF3F2",
    color_accent_soft_dark="#123A48",
    input_background_fill="#FFFFFF",
    input_background_fill_dark=NAVY,
    input_border_color="#E2D8D2",
    input_border_color_dark=NAVY_LINE,
    input_border_color_focus=CYAN,
    input_border_color_focus_dark=CYAN,
    button_primary_background_fill=CYAN,
    button_primary_background_fill_hover="#22C7CB",
    button_primary_background_fill_dark=CYAN,
    button_primary_background_fill_hover_dark="#22C7CB",
    button_primary_text_color=NAVY,
    button_primary_text_color_dark=NAVY,
    button_secondary_background_fill="transparent",
    button_secondary_background_fill_hover="#EFE6E1",
    button_secondary_background_fill_dark="transparent",
    button_secondary_background_fill_hover_dark=NAVY,
    button_secondary_text_color=NAVY,
    button_secondary_text_color_dark=PARCHMENT,
    button_secondary_border_color="#E2D8D2",
    button_secondary_border_color_dark=NAVY_LINE,
    button_cancel_background_fill=APRICOT,
    button_cancel_background_fill_dark=APRICOT,
    button_cancel_text_color=NAVY,
    button_cancel_text_color_dark=NAVY,
    link_text_color=CYAN_DEEP,
    link_text_color_dark=CYAN,
    link_text_color_hover=NAVY,
    link_text_color_hover_dark=APRICOT,
    loader_color=CYAN,
    loader_color_dark=CYAN,
    slider_color=CYAN,
    table_border_color="#E2D8D2",
    table_border_color_dark=NAVY_LINE,
    table_even_background_fill="#FBF8F6",
    table_even_background_fill_dark=NAVY_SURFACE,
    table_odd_background_fill="#F6F0EC",
    table_odd_background_fill_dark="#132739",
    shadow_drop="0 1px 2px rgba(18,38,58,.06)",
    shadow_spread="0 8px 28px rgba(18,38,58,.10)",
)

JS = """
() => {
  // Free scrolling while answers stream: follow new content only while the reader is already at
  // the bottom. Scrolling up to re-read pauses following; scrolling back down (or sending a
  // message, or switching chats) resumes it. Gradio's own autoscroll is off on the chatbot.
  const NEAR_BOTTOM = 80;
  let follow = true;
  let bound = null;
  let observer = null;
  let programmatic = false;

  const toBottom = (el) => { programmatic = true; el.scrollTop = el.scrollHeight; requestAnimationFrame(() => { programmatic = false; }); };

  function bind() {
    const el = document.querySelector('#lm-chatbox .bubble-wrap');
    if (!el || el === bound) return;
    bound = el;
    follow = true;
    el.addEventListener('scroll', () => {
      if (programmatic) return;
      follow = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
    }, { passive: true });
    if (observer) observer.disconnect();
    observer = new MutationObserver(() => { if (follow) toBottom(el); });
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    toBottom(el);
  }

  const resume = () => { follow = true; if (bound) toBottom(bound); };
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && e.target.closest && e.target.closest('#lm-composer')) resume();
  }, true);
  document.addEventListener('click', (e) => {
    if (e.target.closest && e.target.closest('#lm-composer .submit-button, .lm-conv-row button, #lm-new-chat, #lm-chatbox .examples button')) resume();
  }, true);

  setInterval(bind, 800);
  bind();

""" + Path(__file__).with_name("voice.js").read_text(encoding="utf-8") + "}"

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* ================================================================ base */
.gradio-container {{ max-width: 100% !important; padding: 0 !important; }}
footer {{ display: none !important; }}
* {{ scrollbar-width: thin; scrollbar-color: {ASH} transparent; }}
.dark * {{ scrollbar-color: {NAVY_LINE} transparent; }}

/* Gradio paints an orange pending border / progress veil on every running component.
   In a chat app that reads as flicker, so the status pill carries progress instead. */
.pending, .generating, .translucent {{ border-color: transparent !important; opacity: 1 !important; }}
.wrap.default.full, .progress-text, .eta-bar, .meta-text, .meta-text-center {{ display: none !important; }}

/* ================================================================ sidebar
   Deep Space Blue in both schemes. Re-point the theme variables inside it so every
   Gradio component rendered there inherits light-on-navy colours. */
#lm-sidebar, #lm-sidebar .sidebar-content {{
    background: {NAVY} !important;
    border-right: 1px solid {NAVY_LINE} !important;
}}
#lm-sidebar .sidebar-content {{ height: 100vh !important; overflow-y: auto; border-right: none !important; }}
#lm-sidebar-inner {{
    min-height: 100%;
    --body-text-color: {PARCHMENT};
    --body-text-color-subdued: #9FB3B6;
    --block-background-fill: transparent;
    --block-border-color: transparent;
    --background-fill-primary: transparent;
    --input-background-fill: rgba(244,237,234,.07);
    --input-border-color: rgba(197,216,209,.14);
    --input-placeholder-color: rgba(197,216,209,.55);
    --button-secondary-background-fill: transparent;
    --button-secondary-background-fill-hover: rgba(244,237,234,.08);
    --button-secondary-text-color: {PARCHMENT};
    --button-secondary-border-color: transparent;
    color: {PARCHMENT};
    gap: 4px !important;
    padding: 14px 10px 12px !important;
    height: 100%;
}}
.sidebar .toggle-button, .sidebar button[aria-label*="idebar"] {{ color: {PARCHMENT} !important; }}

.lm-brand {{ display:flex; align-items:center; gap:10px; padding: 2px 8px 14px; }}
.lm-brand .lm-mark {{
    width: 30px; height: 30px; border-radius: 9px;
    background: linear-gradient(135deg, {CYAN}, #0A8F93);
    display:grid; place-items:center; color:{NAVY}; font-weight:800; font-size:13px;
    box-shadow: 0 0 0 1px rgba(6,188,193,.35), 0 6px 18px rgba(6,188,193,.25);
}}
.lm-brand .lm-name {{ font-weight: 650; font-size: 16px; letter-spacing: -.2px; color: {PARCHMENT}; }}

#lm-new-chat {{
    background: {CYAN} !important; color: {NAVY} !important; font-weight: 600 !important;
    border-radius: 10px !important; justify-content: flex-start !important;
    padding: 9px 12px !important; box-shadow: 0 4px 14px rgba(6,188,193,.22);
    transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
}}
#lm-new-chat::before, #lm-nav button::before {{
    content: ""; flex: 0 0 16px; width: 16px; height: 16px; margin-right: 10px;
    background-color: currentColor; -webkit-mask: var(--lm-icon) center / contain no-repeat;
    mask: var(--lm-icon) center / contain no-repeat;
}}
#lm-new-chat {{ --lm-icon: {ICON_PLUS}; }}
#lm-nav-chat {{ --lm-icon: {ICON_CHAT}; }}
#lm-nav-kb {{ --lm-icon: {ICON_BOOK}; }}
#lm-nav-search {{ --lm-icon: {ICON_SEARCH}; }}
#lm-nav-tasks {{ --lm-icon: {ICON_TASKS}; }}
#lm-nav-tools {{ --lm-icon: {ICON_TOOLS}; }}
#lm-new-chat:hover {{ background: #22C7CB !important; transform: translateY(-1px); box-shadow: 0 6px 18px rgba(6,188,193,.32); }}

#lm-chat-filter textarea, #lm-chat-filter input {{
    font-size: 13px !important; padding: 8px 11px !important; border-radius: 9px !important;
}}
#lm-chat-filter {{ margin: 8px 0 4px; }}

.lm-group-label {{
    font-size: 11px; font-weight: 600; letter-spacing: .6px; text-transform: uppercase;
    color: rgba(197,216,209,.55); padding: 14px 10px 4px;
}}
#lm-conv-list {{ overflow-y: auto; flex: 1 1 auto; min-height: 120px; gap: 1px !important; }}
.lm-conv-row {{ gap: 0 !important; align-items: center !important; border-radius: 9px; position: relative;
    transition: background .12s ease; flex-wrap: nowrap !important; }}
.lm-conv-row:hover {{ background: rgba(244,237,234,.07); }}
.lm-conv-row.lm-active {{ background: rgba(6,188,193,.14); }}
.lm-conv-row.lm-active::before {{
    content:""; position:absolute; left:0; top:8px; bottom:8px; width:3px; border-radius:3px; background:{CYAN};
}}
.lm-conv-row button {{
    background: transparent !important; border: none !important; box-shadow: none !important;
    color: rgba(244,237,234,.82) !important; font-weight: 400 !important; font-size: 13.5px !important;
    justify-content: flex-start !important; text-align: left !important;
    padding: 8px 10px 8px 13px !important; min-height: 0 !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block !important;
}}
.lm-conv-row.lm-active button {{ color: {PARCHMENT} !important; font-weight: 550 !important; }}
.lm-conv-row .lm-del {{
    flex: 0 0 30px !important; max-width: 30px !important; padding: 6px 0 !important;
    text-align: center !important; opacity: 0; font-size: 13px !important;
    transition: opacity .12s ease;
}}
.lm-conv-row:hover .lm-del {{ opacity: .55; }}
.lm-conv-row .lm-del:hover {{ opacity: 1; color: {APRICOT} !important; }}
.lm-empty {{ color: rgba(197,216,209,.5); font-size: 13px; padding: 10px; }}

#lm-nav {{ border-top: 1px solid rgba(197,216,209,.12); padding-top: 10px; margin-top: 6px; gap: 2px !important; }}
#lm-nav button {{
    justify-content: flex-start !important; font-weight: 500 !important; font-size: 13.5px !important;
    color: rgba(244,237,234,.78) !important; border: none !important; background: transparent !important;
    padding: 8px 10px !important; border-radius: 9px !important;
}}
#lm-nav button:hover {{ background: rgba(244,237,234,.07) !important; color: {PARCHMENT} !important; }}
#lm-nav button.lm-nav-active {{ background: rgba(6,188,193,.14) !important; color: {PARCHMENT} !important; }}
.lm-kb-mini {{ font-size: 11.5px; color: rgba(197,216,209,.55); padding: 8px 10px 0; }}

/* ================================================================ views */
#lm-views > .tab-wrapper, #lm-views > div[role="tablist"], #lm-views .tab-container {{ display: none !important; }}
#lm-views {{ border: none !important; padding: 0 !important; }}
#lm-views > .tabitem, #lm-views .tabitem {{ border: none !important; padding: 0 !important; background: transparent !important; }}

/* Gradio columns are flex children; auto margins don't centre them, align-self does. */
.lm-view {{ max-width: 860px; width: 100%; align-self: center !important; padding: 0 20px !important; }}

#lm-topbar, #lm-topbar .html-container, #lm-topbar .prose {{ padding: 0 !important; width: 100% !important; max-width: none !important; }}
.lm-topbar {{ display:flex; align-items:center; gap: 10px; padding: 14px 4px 6px; min-height: 54px; width: 100%; }}
.lm-title {{ font-weight: 600; font-size: 15px; letter-spacing: -.1px; min-width: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.lm-model {{ font-size: 12px; color: var(--body-text-color-subdued); white-space: nowrap; flex: 0 0 auto; }}
.lm-model::before {{ content: "·"; margin-right: 10px; opacity: .6; }}
.lm-spacer {{ flex: 1 1 auto; }}
.lm-muted {{ color: var(--body-text-color-subdued); }}

.lm-status {{
    display:inline-flex; align-items:center; gap:8px; font-size: 12.5px; font-weight: 500;
    padding: 5px 11px; border-radius: 999px;
    background: var(--color-accent-soft); color: {CYAN_DEEP};
    animation: lm-fade .2s ease;
}}
.dark .lm-status {{ color: {CYAN}; }}
.lm-status-idle {{ display: none; }}
.lm-dot {{ width: 7px; height: 7px; border-radius: 50%; background: {CYAN}; animation: lm-pulse 1.1s ease-in-out infinite; }}
@keyframes lm-pulse {{ 0%,100% {{ opacity:.35; transform:scale(.85); }} 50% {{ opacity:1; transform:scale(1.1); }} }}
@keyframes lm-fade {{ from {{ opacity:0; transform: translateY(-2px); }} to {{ opacity:1; transform:none; }} }}

/* ================================================================ chat */
/* The chat column fills the window and the transcript takes whatever the composer card and the
   footnote leave over, so a toolbar that wraps onto a second row shortens the transcript instead
   of pushing the footnote off the bottom of the screen. */
/* 16px is the page's own top padding above the column. */
#lm-chat-view {{ height: calc(100vh - 16px) !important; }}
#lm-chat-view > #lm-chatbox {{ height: auto !important; flex: 1 1 auto !important; min-height: 160px !important; }}
#lm-chatbox .wrapper {{ min-height: 0 !important; }}
#lm-chatbox .bubble-wrap {{ flex: 1 1 auto !important; min-height: 0 !important; }}
#lm-chatbox {{ border: none !important; background: transparent !important; box-shadow: none !important; }}
#lm-chatbox .bubble-wrap, #lm-chatbox > div {{ background: transparent !important; }}

/* Gradio's clear-chat trash icon wipes the view without touching saved history: remove it.
   Per-message copy buttons appear on hover only, and never on tool panels. */
#lm-chatbox .icon-button-wrapper.top-panel {{ display: none !important; }}
#lm-chatbox .message-buttons {{ opacity: 0; transition: opacity .15s ease; }}
#lm-chatbox .message-row:hover + .message-buttons, #lm-chatbox .message-buttons:hover {{ opacity: 1; }}
#lm-chatbox .message-row:has(.thought-group) + .message-buttons {{ display: none !important; }}
#lm-chatbox .message-buttons .icon-button {{ border: none !important; background: transparent !important; color: var(--body-text-color-subdued) !important; }}

#lm-chatbox .message-row {{ padding: 3px 0 !important; margin: 0 !important; }}
#lm-chatbox .message {{ font-size: 15px !important; line-height: 1.65 !important; }}

/* user: apricot bubble hugging its text, right aligned.
   Gradio sizes each message row to its min-content width, which wraps even short messages
   word by word. Give the row the full width and cap the bubble instead. */
#lm-chatbox .message-row.user-row {{ width: 100% !important; max-width: 100% !important; justify-content: flex-end !important; }}
#lm-chatbox .user-row > .flex-wrap {{ flex: 0 1 auto !important; width: auto !important; max-width: 78% !important; min-width: 0 !important; }}
#lm-chatbox .user-row > .flex-wrap > div, #lm-chatbox .user-row .message.user.panel-full-width {{ width: auto !important; }}
#lm-chatbox .message.user {{
    background: {APRICOT} !important; color: {NAVY} !important; border: none !important;
    border-radius: 18px 18px 5px 18px !important; padding: 10px 16px !important;
    width: auto !important; max-width: 100% !important; margin-left: auto !important;
    overflow-wrap: break-word;
    box-shadow: 0 1px 2px rgba(18,38,58,.08);
}}
#lm-chatbox .message.user * {{ color: {NAVY} !important; }}
#lm-chatbox .user-row img {{ border-radius: 12px; max-height: 240px; }}

/* assistant: no bubble, reads like a document */
#lm-chatbox .message.bot {{
    background: transparent !important; border: none !important; box-shadow: none !important;
    padding: 4px 2px !important; width: 100% !important; max-width: 100% !important;
}}

/* tool + reasoning panels (Gradio renders metadata messages as .thought-group) */
#lm-chatbox .message.bot:has(.thought-group) {{ padding: 2px 0 !important; }}
#lm-chatbox .thought-group {{
    border: 1px solid var(--border-color-primary) !important;
    border-left: 3px solid {CYAN} !important;
    background: var(--background-fill-primary) !important;
    border-radius: 11px !important; padding: 7px 12px !important;
    transition: border-color .15s ease;
}}
#lm-chatbox .thought-group:hover {{ border-color: {ASH} !important; border-left-color: {CYAN} !important; }}
.dark #lm-chatbox .thought-group:hover {{ border-color: {NAVY_LINE} !important; border-left-color: {CYAN} !important; }}
#lm-chatbox .thought-group .title {{
    font-size: 13px !important; font-weight: 500 !important; color: var(--body-text-color-subdued) !important;
    display: flex; align-items: center; gap: 6px; cursor: pointer;
}}
#lm-chatbox .thought-group .title p {{ margin: 0 !important; }}
#lm-chatbox .thought-group .duration {{ font-size: 11.5px !important; opacity: .75; margin-left: auto; font-variant-numeric: tabular-nums; }}
#lm-chatbox .thought-group .content {{
    font-size: 13.5px !important; line-height: 1.55 !important;
    margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-color-primary);
}}

#lm-chatbox pre, #lm-chatbox code {{ font-family: var(--font-mono) !important; }}
#lm-chatbox pre {{ border-radius: 10px !important; border: 1px solid var(--border-color-primary) !important; }}
#lm-chatbox a {{ text-decoration: underline; text-underline-offset: 2px; text-decoration-thickness: 1px; }}
#lm-chatbox table {{ border-collapse: collapse; font-size: 14px; }}

/* empty state + starters */
.lm-hero {{ text-align:center; padding: 8vh 0 18px; animation: lm-fade .35s ease; }}
.lm-hero .lm-hero-mark {{
    width: 52px; height: 52px; margin: 0 auto 16px; border-radius: 15px;
    background: linear-gradient(135deg, {CYAN}, #0A8F93); display:grid; place-items:center;
    color:{NAVY}; font-weight:800; font-size:20px; box-shadow: 0 10px 30px rgba(6,188,193,.3);
}}
.lm-hero h2 {{ font-size: 26px; font-weight: 650; letter-spacing: -.5px; margin: 0 0 6px; }}
.lm-hero p {{ color: var(--body-text-color-subdued); font-size: 14.5px; margin: 0; }}
#lm-chatbox .examples {{ max-width: 680px; margin: 0 auto; gap: 10px !important; }}
#lm-chatbox .example {{
    border: 1px solid var(--border-color-primary) !important; background: var(--background-fill-primary) !important;
    border-radius: 14px !important; padding: 12px 14px !important; text-align: left !important;
    transition: border-color .12s ease, transform .12s ease, box-shadow .12s ease;
}}
#lm-chatbox .example:hover {{ border-color: {CYAN} !important; transform: translateY(-1px); box-shadow: var(--shadow-spread); }}

/* composer card: text box on top, model picker + tool chips underneath, one rounded surface */
#lm-composer-card {{
    border: 1px solid var(--border-color-primary) !important; border-radius: 22px !important;
    background: var(--background-fill-primary) !important; box-shadow: var(--shadow-spread) !important;
    padding: 4px 8px 8px !important; gap: 0 !important; overflow: visible !important;
    transition: border-color .15s ease, box-shadow .15s ease;
}}
#lm-composer-card:focus-within {{ border-color: {CYAN} !important; box-shadow: 0 0 0 3px rgba(6,188,193,.16), var(--shadow-spread) !important; }}
#lm-composer-card > div, #lm-composer-card .styler {{ background: transparent !important; border: none !important; box-shadow: none !important; gap: 0 !important; }}
#lm-composer {{ border: none !important; background: transparent !important; box-shadow: none !important; padding: 0 2px !important; }}
/* MultimodalTextbox draws its own framed box inside; the card is the frame now. */
#lm-composer div, #lm-composer label {{ border-color: transparent !important; box-shadow: none !important; outline: none !important; }}
#lm-composer .full-container, #lm-composer .input-container {{ background: transparent !important; }}
#lm-composer textarea {{
    border: none !important; box-shadow: none !important; background: transparent !important;
    font-size: 15px !important; line-height: 1.5 !important; padding: 8px 4px !important;
}}
#lm-composer button.submit-button, #lm-composer .submit-button {{
    background: {CYAN} !important; color: {NAVY} !important; border-radius: 50% !important;
    transition: transform .12s ease, background .12s ease;
}}
#lm-composer .submit-button:hover {{ background: #22C7CB !important; transform: scale(1.05); }}
#lm-composer .stop-button {{ background: {APRICOT} !important; color: {NAVY} !important; border-radius: 50% !important; }}
#lm-composer .upload-button {{ color: var(--body-text-color-subdued) !important; }}
#lm-composer .upload-button:hover {{ color: {CYAN_DEEP} !important; }}
.dark #lm-composer .upload-button:hover {{ color: {CYAN} !important; }}

#lm-toolbar {{
    gap: 6px !important; align-items: center !important; flex-wrap: wrap !important;
    padding: 2px 4px 0 !important; background: transparent !important;
}}
#lm-toolbar > * {{ flex: 0 0 auto !important; min-width: 0 !important; }}

/* model picker: a quiet pill, not a form field */
#lm-model-picker, #lm-model-picker > div, #lm-model-picker label {{
    width: auto !important; padding: 0 !important; margin: 0 !important;
    background: transparent !important; border: none !important; box-shadow: none !important; min-height: 0 !important;
}}
#lm-model-picker .wrap, #lm-model-picker .wrap-inner, #lm-model-picker .secondary-wrap, #lm-model-picker input {{
    background: transparent !important; border: none !important; box-shadow: none !important;
}}
#lm-model-picker .wrap {{
    border: 1px solid var(--border-color-primary) !important; border-radius: 999px !important;
    padding: 0 8px 0 12px !important; min-height: 30px !important; height: 30px !important;
    transition: border-color .12s ease, background .12s ease;
}}
#lm-model-picker .wrap:hover {{ background: var(--background-fill-secondary) !important; }}
#lm-model-picker input {{
    font-size: 13px !important; font-weight: 600 !important; width: 23ch !important; cursor: pointer;
    padding: 0 !important; height: 28px !important; text-overflow: ellipsis;
}}
#lm-model-picker ul.options {{ border-radius: 12px !important; box-shadow: var(--shadow-spread) !important; font-size: 13.5px; min-width: 220px; }}

/* tool chips */
.lm-chip {{
    display: inline-flex !important; align-items: center; gap: 7px;
    border: 1px solid var(--border-color-primary) !important; border-radius: 999px !important;
    background: transparent !important; color: var(--body-text-color-subdued) !important;
    font-size: 13px !important; font-weight: 500 !important; padding: 5px 12px 5px 10px !important;
    min-height: 30px !important; box-shadow: none !important;
    transition: background .12s ease, color .12s ease, border-color .12s ease;
}}
.lm-chip::before {{
    content: ""; width: 15px; height: 15px; flex: 0 0 15px; background-color: currentColor;
    -webkit-mask: var(--lm-icon) center / contain no-repeat; mask: var(--lm-icon) center / contain no-repeat;
}}
.lm-chip:hover {{ background: var(--background-fill-secondary) !important; color: var(--body-text-color) !important; }}
.lm-chip.lm-chip-on {{
    background: var(--color-accent-soft) !important; border-color: {CYAN} !important; color: {CYAN_DEEP} !important;
}}
.dark .lm-chip.lm-chip-on {{ color: {CYAN} !important; }}
.lm-chip.lm-chip-locked {{ opacity: .85; cursor: default; }}
.lm-chip.lm-chip-disabled {{ opacity: .4; cursor: not-allowed; }}
#lm-export {{ --lm-icon: {ICON_DOWNLOAD}; margin-left: auto !important; }}
/* Hidden download target: the PDF button builds the file, then clicks this programmatically. */
#lm-export-file, #lm-export-file * {{ position: absolute !important; width: 1px !important; height: 1px !important; opacity: 0 !important; pointer-events: none !important; overflow: hidden !important; }}

/* KV cache picker: same quiet pill as the model picker, a notch smaller */
#lm-kv-picker, #lm-kv-picker > div, #lm-kv-picker label, #lm-scope-picker, #lm-scope-picker > div, #lm-scope-picker label {{
    width: auto !important; padding: 0 !important; margin: 0 !important;
    background: transparent !important; border: none !important; box-shadow: none !important; min-height: 0 !important;
}}
#lm-kv-picker .wrap, #lm-kv-picker .wrap-inner, #lm-kv-picker .secondary-wrap, #lm-kv-picker input, #lm-scope-picker .wrap, #lm-scope-picker .wrap-inner, #lm-scope-picker .secondary-wrap, #lm-scope-picker input {{
    background: transparent !important; border: none !important; box-shadow: none !important;
}}
#lm-kv-picker .wrap, #lm-scope-picker .wrap {{
    border: 1px solid var(--border-color-primary) !important; border-radius: 999px !important;
    padding: 0 8px 0 10px !important; min-height: 30px !important; height: 30px !important;
}}
#lm-kv-picker .wrap:hover, #lm-scope-picker .wrap:hover {{ background: var(--background-fill-secondary) !important; }}
#lm-kv-picker input, #lm-scope-picker input {{
    font-size: 12.5px !important; font-weight: 500 !important; width: 17ch !important; cursor: pointer;
    padding: 0 !important; height: 28px !important; color: var(--body-text-color-subdued) !important;
    font-variant-numeric: tabular-nums;
}}

#lm-scope-picker input {{ width: 15ch !important; }}
.lm-sections {{ display: flex; flex-direction: column; gap: 4px; font-size: 13.5px; margin-bottom: 8px; }}
.lm-section-row {{ display: flex; align-items: center; gap: 8px; }}
.lm-section-row .lm-muted {{ margin-left: auto; font-size: 12.5px; }}

.lm-batch {{ border: 1px solid var(--border-color-primary); border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; }}
.lm-batch-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
.lm-task {{ display: flex; gap: 8px; align-items: baseline; font-size: 13.5px; padding: 2px 0; }}
.lm-task-title {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.lm-task-error {{ font-size: 12.5px; color: #B4513F; margin: 0 0 4px 26px; }}
.lm-request {{ border: 1px solid var(--border-color-primary); border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; font-size: 13.5px; }}
.lm-request code {{ font-size: 12px; overflow-wrap: anywhere; }}

/* a chat still answering in the background */
.lm-conv-row.lm-busy > button:first-child {{ padding-right: 22px !important; }}
.lm-conv-row.lm-busy::after {{
    content: ""; position: absolute; right: 38px; top: 50%; width: 7px; height: 7px; margin-top: -3.5px;
    border-radius: 50%; background: {CYAN}; animation: lm-pulse 1.1s ease-in-out infinite; pointer-events: none;
}}
#lm-chip-web {{ --lm-icon: {ICON_GLOBE}; }}
#lm-chip-kb {{ --lm-icon: {ICON_BOOK}; }}
#lm-chip-think {{ --lm-icon: {ICON_SPARK}; }}
#lm-chip-voice {{ --lm-icon: {ICON_MIC}; }}

/* voice conversation: a status strip above the composer while Voice is on */
#lm-voice-bar {{
    display: flex; align-items: center; gap: 10px; align-self: center; width: fit-content !important;
    margin: 0 auto -6px; padding: 6px 8px 6px 14px; border-radius: 999px;
    background: var(--background-fill-primary); border: 1px solid var(--border-color-primary);
    box-shadow: var(--shadow-drop); font-size: 13px; color: var(--body-text-color); max-width: 100%;
}}
#lm-voice-bar[hidden] {{ display: none !important; }}
#lm-voice-bar .lm-vb-label {{ min-width: 0; overflow-wrap: anywhere; }}
#lm-voice-bar .lm-vb-meter {{ display: inline-flex; align-items: center; gap: 3px; height: 18px; flex: none; }}
#lm-voice-bar .lm-vb-meter i {{
    display: block; width: 3px; height: 18px; border-radius: 2px; background: {CYAN};
    transform: scaleY(.15); transition: transform 60ms linear;
}}
#lm-voice-bar.lm-vb-starting .lm-vb-meter i, #lm-voice-bar.lm-vb-transcribing .lm-vb-meter i,
#lm-voice-bar.lm-vb-waiting .lm-vb-meter i {{ animation: lm-vb-wait 1.2s ease-in-out infinite; transition: none; }}
#lm-voice-bar.lm-vb-speaking .lm-vb-meter i {{ animation: lm-vb-talk .9s ease-in-out infinite; transition: none; background: {CYAN_DEEP}; }}
.dark #lm-voice-bar.lm-vb-speaking .lm-vb-meter i {{ background: {APRICOT}; }}
#lm-voice-bar .lm-vb-meter i:nth-child(2) {{ animation-delay: .12s; }}
#lm-voice-bar .lm-vb-meter i:nth-child(3) {{ animation-delay: .24s; }}
#lm-voice-bar .lm-vb-meter i:nth-child(4) {{ animation-delay: .36s; }}
#lm-voice-bar .lm-vb-meter i:nth-child(5) {{ animation-delay: .48s; }}
#lm-voice-bar.lm-vb-error {{ border-color: #B4513F; }}
#lm-voice-bar.lm-vb-error .lm-vb-meter {{ display: none; }}
#lm-voice-bar .lm-vb-action {{
    flex: none; border: 1px solid var(--border-color-primary); background: transparent; color: inherit;
    border-radius: 999px; padding: 3px 12px; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer;
}}
#lm-voice-bar .lm-vb-action:hover {{ border-color: {CYAN}; }}
#lm-voice-bar .lm-vb-action[hidden] {{ display: none; }}
@keyframes lm-vb-wait {{ 0%, 100% {{ transform: scaleY(.2); opacity: .5; }} 50% {{ transform: scaleY(.45); opacity: 1; }} }}
@keyframes lm-vb-talk {{ 0%, 100% {{ transform: scaleY(.3); }} 50% {{ transform: scaleY(.9); }} }}
@media (prefers-reduced-motion: reduce) {{ #lm-voice-bar .lm-vb-meter i {{ animation: none !important; }} }}

.lm-badge {{
    display: inline-block; font-size: 10.5px; font-weight: 600; letter-spacing: .3px; text-transform: uppercase;
    padding: 1px 6px; border-radius: 6px; margin-left: 4px; vertical-align: 1px;
    background: var(--background-fill-secondary); color: var(--body-text-color-subdued);
}}
.lm-badge-cloud {{ background: {APRICOT}; color: {NAVY}; }}

/* status HUD: always visible, top right of the window */
#lm-hud {{ position: fixed !important; top: 12px; right: 18px; z-index: 60; width: auto !important; padding: 0 !important; background: transparent !important; border: none !important; }}
#lm-hud .html-container, #lm-hud .prose {{ padding: 0 !important; }}
.lm-hud {{ display: flex; gap: 6px; align-items: center; }}
.lm-hud-pill {{
    display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-variant-numeric: tabular-nums;
    padding: 4px 10px; border-radius: 999px; white-space: nowrap;
    background: var(--background-fill-primary); border: 1px solid var(--border-color-primary);
    color: var(--body-text-color-subdued); box-shadow: var(--shadow-drop);
}}
.lm-hud-pill b {{ font-weight: 600; color: var(--body-text-color); font-size: 11px; letter-spacing: .3px; text-transform: uppercase; }}
.lm-meter {{ display: inline-block; width: 38px; height: 5px; border-radius: 3px; background: var(--background-fill-secondary); overflow: hidden; }}
.lm-meter > i {{ display: block; height: 100%; background: {CYAN}; border-radius: 3px; transition: width .4s ease; }}
.lm-hud-warm {{ border-color: {APRICOT}; }}
.lm-hud-warm .lm-meter > i {{ background: #E9A86A; }}
.lm-hud-hot {{ border-color: #D9534F; color: var(--body-text-color); }}
.lm-hud-hot .lm-meter > i {{ background: #D9534F; }}
@media (max-width: 900px) {{
    #lm-hud {{ position: static !important; }}
    .lm-hud {{ flex-wrap: wrap; justify-content: flex-end; padding: 8px 12px 0; }}
}}
/* keep the chat title clear of the HUD */
.lm-topbar {{ padding-right: 340px !important; }}
@media (max-width: 1300px) {{ .lm-topbar {{ padding-right: 0 !important; padding-top: 44px !important; }} }}

.lm-footnote {{ font-size: 11.5px; color: var(--body-text-color-subdued); text-align:center; padding: 8px 0 14px; opacity: .8; }}
.lm-footnote-cloud {{ opacity: 1; color: var(--body-text-color); }}
.lm-footnote-cloud b {{ color: #B4513F; }}
.dark .lm-footnote-cloud b {{ color: {APRICOT}; }}

/* ================================================================ knowledge + search */
.lm-page-head {{ padding: 26px 4px 14px; }}
.lm-page-head h2 {{ font-size: 22px; font-weight: 650; letter-spacing: -.4px; margin: 0 0 4px; }}
.lm-page-head p {{ color: var(--body-text-color-subdued); margin: 0; font-size: 14px; }}
.lm-card {{
    border: 1px solid var(--border-color-primary) !important; border-radius: 16px !important;
    background: var(--background-fill-primary) !important; padding: 16px !important;
}}
.lm-card-title {{ font-weight: 600; font-size: 14px; margin-bottom: 4px; }}
.lm-stats {{ display: flex; gap: 22px; margin-top: 12px; }}
.lm-stat {{ display:inline-flex; gap: 6px; align-items: baseline; font-size: 13px; color: var(--body-text-color-subdued); }}
#lm-sources td, #lm-sources th, #lm-sources td *, #lm-sources th * {{
    font-family: var(--font) !important; font-size: 13.5px !important; overflow-wrap: anywhere; word-break: normal;
}}
#lm-sources th, #lm-sources th * {{ font-weight: 600 !important; }}
#lm-sources tr {{ cursor: pointer; }}
#lm-search-input, #lm-search-input > label, #lm-search-input .wrap {{ background: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; }}
#lm-search-input textarea, #lm-search-input input {{
    border: 1px solid var(--border-color-primary) !important; border-radius: 12px !important;
    background: var(--background-fill-primary) !important; padding: 12px 14px !important; font-size: 15px !important;
}}
#lm-search-input textarea:focus, #lm-search-input input:focus {{ border-color: {CYAN} !important; box-shadow: 0 0 0 3px rgba(6,188,193,.16) !important; }}
.lm-stat b {{ font-size: 20px; color: var(--body-text-color); font-weight: 650; }}

.hit-card {{
    border: 1px solid var(--border-color-primary); border-left: 3px solid {CYAN};
    border-radius: 12px; padding: 12px 16px; margin-bottom: 10px;
    background: var(--background-fill-primary); animation: lm-fade .2s ease;
}}
.hit-card .hit-meta {{ font-size: 12px; color: var(--body-text-color-subdued); margin-bottom: 6px; font-family: var(--font-mono); }}
.hit-card .hit-text {{ font-size: 14px; line-height: 1.55; white-space: pre-wrap; }}
.hit-score {{ float: right; font-weight: 600; color: {CYAN_DEEP}; }}
.dark .hit-score {{ color: {CYAN}; }}
"""
