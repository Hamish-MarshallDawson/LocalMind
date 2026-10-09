"""LocalMind visual theme — the neo-brutalist system from hamishmarshalldawson.com.

Palette: exactly three colours, no greys, no gradients, no blurred shadows.
  paper  #FFFFFF   page and plates in light mode, text and rules in dark
  ink    #000000   text and rules in light mode, page and plates in dark
  signal #1F1FFF   the one accent: active states, send, focus, shadow plates on ink

Pairing rules that keep every text pair above 4.5:1 (WCAG 2.2 AA):
  ink on paper      21:1    yes
  paper on ink      21:1    yes
  paper on signal   7.8:1   yes
  signal on paper   7.8:1   yes   (light mode only)
  signal on ink     2.7:1   never — on ink, signal is a block colour, never text
So "on" states are a signal plate with paper text in both schemes, rather than
signal-coloured text, which only clears contrast on paper.

Geometry: square. Borders are 1/2/3/4px (--bw-*), shadows are a second solid
plate offset by --off-* with zero blur, and objects move by exactly one offset
step on hover, press and focus (the .u-press contract). Alarm red #E10600 is the
only fourth colour, reserved for destructive and over-budget states.

Changing --signal in LM_TOKENS below re-colours the whole app.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import gradio as gr


def _icon(body: str) -> str:
    """A Lucide-style stroke icon as a CSS mask, so it takes the button's text colour."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
        f"stroke-width='2.25' stroke-linecap='square' stroke-linejoin='miter'>{body}</svg>"
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

PAPER = "#FFFFFF"
INK = "#000000"
SIGNAL = "#1F1FFF"
ALARM = "#E10600"

# Where Gradio insists on a mid-tone (a dropdown list hover, a disabled fill) these are
# the only two it gets: flat washes of ink on paper and paper on ink, never a grey ramp.
WASH_LIGHT = "#F2F2F2"
WASH_DARK = "#141414"

_signal = gr.themes.Color(
    name="lm_signal",
    c50="#EFEFFF", c100="#DEDEFF", c200="#BDBDFF", c300="#9C9CFF", c400="#5C5CFF",
    c500=SIGNAL, c600="#1818D6", c700="#1414AD", c800="#0F0F85", c900="#0A0A5C", c950="#05052E",
)
_mono = gr.themes.Color(
    name="lm_mono",
    c50="#FFFFFF", c100="#F2F2F2", c200="#E0E0E0", c300="#C4C4C4", c400="#9A9A9A",
    c500="#6E6E6E", c600="#4A4A4A", c700="#2B2B2B", c800=WASH_DARK, c900="#0A0A0A", c950=INK,
)

THEME = gr.themes.Base(
    primary_hue=_signal,
    secondary_hue=_mono,
    neutral_hue=_mono,
    radius_size=gr.themes.sizes.radius_none,
    # Plain strings, not gr.themes.GoogleFont: Gradio 6.27's launch() compares theme fonts
    # against built-in themes and crashes when a GoogleFont meets a str. The webfonts are
    # loaded by an @import in CSS instead, and fall back to system fonts offline.
    font=["Archivo", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"],
    font_mono=["JetBrains Mono", "ui-monospace", "Consolas", "monospace"],
).set(
    body_background_fill=PAPER,
    body_background_fill_dark=INK,
    body_text_color=INK,
    body_text_color_dark=PAPER,
    body_text_color_subdued="#4A4A4A",
    body_text_color_subdued_dark="#B8B8B8",
    background_fill_primary=PAPER,
    background_fill_primary_dark=INK,
    background_fill_secondary=WASH_LIGHT,
    background_fill_secondary_dark=WASH_DARK,
    block_background_fill=PAPER,
    block_background_fill_dark=INK,
    block_border_color=INK,
    block_border_color_dark=PAPER,
    block_border_width="3px",
    block_shadow="none",
    block_label_text_color=INK,
    block_label_text_color_dark=PAPER,
    border_color_primary=INK,
    border_color_primary_dark=PAPER,
    color_accent=SIGNAL,
    color_accent_soft=SIGNAL,
    color_accent_soft_dark=SIGNAL,
    input_background_fill=PAPER,
    input_background_fill_dark=INK,
    input_border_color=INK,
    input_border_color_dark=PAPER,
    input_border_width="2px",
    input_border_color_focus=SIGNAL,
    input_border_color_focus_dark=SIGNAL,
    button_large_radius="0",
    button_small_radius="0",
    button_primary_background_fill=SIGNAL,
    button_primary_background_fill_hover=SIGNAL,
    button_primary_background_fill_dark=SIGNAL,
    button_primary_background_fill_hover_dark=SIGNAL,
    button_primary_text_color=PAPER,
    button_primary_text_color_dark=PAPER,
    button_primary_border_color=INK,
    button_primary_border_color_dark=PAPER,
    button_secondary_background_fill=PAPER,
    button_secondary_background_fill_hover=PAPER,
    button_secondary_background_fill_dark=INK,
    button_secondary_background_fill_hover_dark=INK,
    button_secondary_text_color=INK,
    button_secondary_text_color_dark=PAPER,
    button_secondary_border_color=INK,
    button_secondary_border_color_dark=PAPER,
    button_cancel_background_fill=ALARM,
    button_cancel_background_fill_dark=ALARM,
    button_cancel_text_color=PAPER,
    button_cancel_text_color_dark=PAPER,
    link_text_color=SIGNAL,
    link_text_color_dark=PAPER,
    link_text_color_hover=INK,
    link_text_color_hover_dark=SIGNAL,
    loader_color=SIGNAL,
    loader_color_dark=SIGNAL,
    slider_color=SIGNAL,
    table_border_color=INK,
    table_border_color_dark=PAPER,
    table_even_background_fill=PAPER,
    table_even_background_fill_dark=INK,
    table_odd_background_fill=WASH_LIGHT,
    table_odd_background_fill_dark=WASH_DARK,
    shadow_drop="4px 4px 0 0 var(--lm-shadow)",
    shadow_spread="8px 8px 0 0 var(--lm-shadow)",
)

# Gradio rewrites every selector in CSS below to sit under ".contain", so a rule there can
# never reach the page wrapper above it. On a phone that wrapper's 32px gutters cost a sixth
# of the screen, so this one rule is added to the document unscoped instead.
PAGE_GUTTER_CSS = (
    "@media (max-width: 760px) { .gradio-container .main.fillable "
    "{ padding-left: 8px !important; padding-right: 8px !important; } }"
)

JS = """
() => {
  const gutter = document.createElement('style');
  gutter.textContent = %r;
  document.head.appendChild(gutter);
""" % PAGE_GUTTER_CSS + """
  // Free scrolling while answers stream: follow new content only while the reader is already at
  // the bottom. Scrolling up to re-read pauses following; scrolling back down (or sending a
  // message, or switching chats) resumes it. Gradio's own autoscroll is off on the chatbot.
  const NEAR_BOTTOM = 80;
  let follow = true;
  let bound = null;
  let observer = null;
  let programmatic = false;

  const toBottom = (el) => {
    if (!hasTranscript()) { el.scrollTop = 0; return; }
    programmatic = true; el.scrollTop = el.scrollHeight; requestAnimationFrame(() => { programmatic = false; });
  };

  // An empty chat shows the welcome panel instead of messages; scrolling that to the bottom
  // would hide the headline, so following only applies once there is a transcript.
  const hasTranscript = () => !document.querySelector('#lm-chatbox .lm-hero');

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

  // Gradio sizes the message box by measuring it once on mount. That measurement can land
  // before the layout and the webfonts have settled, and it then clamps the box to max_lines
  // (twelve), which swallows most of the transcript until you type. Re-fit it from its real
  // content height whenever it is empty; while you are typing, Gradio's own sizing is left alone.
  function fitComposer() {
    const t = document.querySelector('#lm-composer textarea');
    if (!t || t.value) return;
    const natural = (t.style.height = 'auto', t.scrollHeight);
    t.style.height = natural + 'px';
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitComposer);

  setInterval(() => { bind(); fitComposer(); }, 800);
  bind();

""" + Path(__file__).with_name("voice.js").read_text(encoding="utf-8") + "}"


# Only the palette and the icon masks are interpolated; everything below reads these
# custom properties, so no rule hard-codes a colour (and the CSS needs no brace escaping).
LM_TOKENS = f"""
:root {{
    --paper: {PAPER};
    --ink: {INK};
    --signal: {SIGNAL};
    --alarm: {ALARM};

    /* surface contract — redeclared by .dark and by .lm-on-ink */
    --lm-surface: var(--paper);
    --lm-on-surface: var(--ink);
    --lm-line: var(--ink);
    --lm-shadow: var(--ink);
    --lm-muted: #4A4A4A;
    --lm-wash: {WASH_LIGHT};
    --lm-hover: rgba(0, 0, 0, .06);
    --lm-accent-text: var(--signal);
    --lm-user-fill: var(--ink);
    --lm-user-text: var(--paper);

    /* geometry */
    --bw-hair: 1px;
    --bw-rule: 2px;
    --bw-frame: 3px;
    --bw-heavy: 4px;
    --off-1: 4px;
    --off-2: 8px;
    --off-3: 12px;

    /* type */
    --lm-sans: "Archivo", "Helvetica Neue", Helvetica, Arial, sans-serif;
    --lm-mono: "JetBrains Mono", ui-monospace, Consolas, monospace;
    --lm-pixel: "Silkscreen", "JetBrains Mono", ui-monospace, monospace;
    --wdth-compressed: 62;
    --wdth-condensed: 75;
    --wdth-normal: 100;
    --tr-micro: .06em;

    /* motion */
    --ease-snap: cubic-bezier(.7, 0, .2, 1);
    --dur-1: 90ms;
    --dur-2: 160ms;

    --icon-plus: {ICON_PLUS};
    --icon-chat: {ICON_CHAT};
    --icon-book: {ICON_BOOK};
    --icon-search: {ICON_SEARCH};
    --icon-globe: {ICON_GLOBE};
    --icon-download: {ICON_DOWNLOAD};
    --icon-mic: {ICON_MIC};
    --icon-tasks: {ICON_TASKS};
    --icon-tools: {ICON_TOOLS};
    --icon-spark: {ICON_SPARK};
}}

/* Dark mode is the same system with paper and ink swapped; the shadow plate becomes
   signal, because an ink shadow is invisible on an ink page. */
.dark, .lm-on-ink {{
    --lm-surface: var(--ink);
    --lm-on-surface: var(--paper);
    --lm-line: var(--paper);
    --lm-shadow: var(--signal);
    --lm-muted: #B8B8B8;
    --lm-wash: {WASH_DARK};
    --lm-hover: rgba(255, 255, 255, .09);
    --lm-accent-text: var(--paper);
    --lm-user-fill: var(--paper);
    --lm-user-text: var(--ink);
}}
"""


CSS = LM_TOKENS + """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=JetBrains+Mono:wght@400;500;700&family=Silkscreen:wght@400;700&display=swap');

/* ================================================================ type utilities
   Ported from the portfolio: Archivo's width axis is the whole display system —
   compressed black for mega rows, condensed for titles, normal for reading. */
/* Bound by width and by height: the headline shares the transcript panel with the
   starters, so it may never grow past what is left above the message box. */
.lm-mega {
    font-family: var(--lm-sans); font-weight: 900;
    font-variation-settings: "wdth" var(--wdth-compressed);
    font-size: clamp(1.5rem, min(3.6vw, (100svh - 30rem) / 4.5), 3.5rem);
    line-height: .86; letter-spacing: -.035em; text-transform: uppercase;
}
.lm-display {
    font-family: var(--lm-sans); font-weight: 900;
    font-variation-settings: "wdth" var(--wdth-condensed);
    font-size: clamp(1.6rem, 1.1rem + 1.6vw, 2.5rem);
    line-height: .92; letter-spacing: -.025em; text-transform: uppercase;
}
.lm-micro, .lm-group-label, .lm-cell, .lm-chip, .lm-badge, .lm-hud-pill,
.lm-card-title, .lm-status, #lm-nav button, #lm-new-chat {
    font-family: var(--lm-mono); letter-spacing: var(--tr-micro); text-transform: uppercase;
}
/* Whole sentences stay sentence case — mono small caps are for labels, not prose. */
.lm-footnote { font-family: var(--lm-mono); letter-spacing: .01em; }
.lm-num { font-family: var(--lm-pixel); font-weight: 400; letter-spacing: 0; font-variant-numeric: tabular-nums; }
.lm-outline { color: transparent; -webkit-text-stroke: max(1.5px, .012em) var(--lm-on-surface); }

/* The one interaction model: an object rests on its shadow plate, hover lifts it a
   step, press pushes it flat, focus shifts the fill to signal as well as lifting. */
.lm-press {
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow);
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap),
                background-color 0s, color 0s;
}
@media (hover: hover) and (pointer: fine) {
    .lm-press:hover { transform: translate(-2px, -2px); box-shadow: calc(var(--off-1) + 2px) calc(var(--off-1) + 2px) 0 0 var(--lm-shadow); }
}
.lm-press:active { transform: translate(var(--off-1), var(--off-1)); box-shadow: 0 0 0 0 var(--lm-shadow) !important; }

/* ================================================================ base */
.gradio-container { max-width: 100% !important; padding: 0 !important; }
body, .gradio-container { font-family: var(--lm-sans); font-variation-settings: "wdth" var(--wdth-normal); }
footer { display: none !important; }
* { scrollbar-width: thin; scrollbar-color: var(--lm-line) transparent; border-radius: 0 !important; }
:focus-visible { outline: var(--bw-frame) solid var(--signal); outline-offset: 2px; }
::selection { background: var(--signal); color: var(--paper); }

/* Gradio paints an orange pending border / progress veil on every running component.
   In a chat app that reads as flicker, so the status plate carries progress instead. */
.pending, .generating, .translucent { border-color: var(--lm-line) !important; opacity: 1 !important; }
.wrap.default.full, .progress-text, .eta-bar, .meta-text, .meta-text-center { display: none !important; }

/* Marching hazard stripes: the project's one piece of continuous motion, used only
   where something is genuinely in flight. Hard colour stops, so it reads as stripes. */
@keyframes lm-march { to { background-position: 48px 0; } }
@keyframes lm-blink { 50% { opacity: 0; } }
@keyframes lm-rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.lm-hazard {
    background-image: repeating-linear-gradient(-45deg, var(--signal) 0 8px, transparent 8px 16px);
    background-size: 48px 100%; animation: lm-march 1.1s linear infinite;
}

/* ================================================================ sidebar
   Always an ink surface, in both schemes. .lm-on-ink re-points the surface contract
   and the Gradio variables, so every component rendered inside inherits it. */
#lm-sidebar, #lm-sidebar .sidebar-content {
    background: var(--ink) !important;
    border-right: var(--bw-frame) solid var(--signal) !important;
}
#lm-sidebar .sidebar-content { height: 100vh !important; overflow-y: auto; border-right: none !important; }
#lm-sidebar-inner {
    min-height: 100%;
    --lm-surface: var(--ink);
    --lm-on-surface: var(--paper);
    --lm-line: var(--paper);
    --lm-shadow: var(--signal);
    --lm-muted: #B8B8B8;
    --lm-hover: rgba(255, 255, 255, .09);
    --body-text-color: var(--paper);
    --body-text-color-subdued: #B8B8B8;
    --block-background-fill: transparent;
    --block-border-color: var(--paper);
    --background-fill-primary: transparent;
    --input-background-fill: transparent;
    --input-border-color: var(--paper);
    --input-placeholder-color: rgba(255, 255, 255, .5);
    --button-secondary-background-fill: transparent;
    --button-secondary-background-fill-hover: transparent;
    --button-secondary-text-color: var(--paper);
    --button-secondary-border-color: var(--paper);
    color: var(--paper);
    gap: 0 !important;
    padding: 14px 12px 12px !important;
    height: 100%;
}
.sidebar .toggle-button, .sidebar button[aria-label*="idebar"] { color: var(--paper) !important; }

.lm-brand { display: flex; align-items: center; gap: 10px; padding: 2px 0 14px; }
.lm-brand .lm-mark {
    width: 30px; height: 30px; flex: none; display: grid; place-items: center;
    background: var(--signal); color: var(--paper);
    font-family: var(--lm-pixel); font-size: 11px; letter-spacing: 0;
    border: var(--bw-rule) solid var(--paper); box-shadow: var(--off-1) var(--off-1) 0 0 var(--paper);
}
.lm-brand .lm-name {
    font-weight: 900; font-size: 19px; line-height: 1; color: var(--paper);
    font-variation-settings: "wdth" var(--wdth-condensed); letter-spacing: -.02em; text-transform: uppercase;
}

#lm-new-chat {
    background: var(--signal) !important; color: var(--paper) !important;
    border: var(--bw-rule) solid var(--paper) !important;
    font-weight: 700 !important; font-size: 12px !important;
    justify-content: flex-start !important; padding: 10px 12px !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--paper);
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap);
}
#lm-new-chat:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--paper); }
#lm-new-chat:active { transform: translate(var(--off-1), var(--off-1)); box-shadow: none; }
#lm-new-chat::before, #lm-nav button::before {
    content: ""; flex: 0 0 15px; width: 15px; height: 15px; margin-right: 10px;
    background-color: currentColor; -webkit-mask: var(--lm-icon) center / contain no-repeat;
    mask: var(--lm-icon) center / contain no-repeat;
}
#lm-new-chat { --lm-icon: var(--icon-plus); }
#lm-nav-chat { --lm-icon: var(--icon-chat); }
#lm-nav-kb { --lm-icon: var(--icon-book); }
#lm-nav-search { --lm-icon: var(--icon-search); }
#lm-nav-tasks { --lm-icon: var(--icon-tasks); }
#lm-nav-tools { --lm-icon: var(--icon-tools); }

#lm-chat-filter { margin: 12px 0 2px; }
#lm-chat-filter textarea, #lm-chat-filter input {
    font-family: var(--lm-mono) !important; font-size: 12px !important; padding: 7px 10px !important;
    border: var(--bw-rule) solid var(--paper) !important; background: transparent !important;
    color: var(--paper) !important;
}
#lm-chat-filter textarea:focus, #lm-chat-filter input:focus { border-color: var(--signal) !important; box-shadow: none !important; }

.lm-group-label {
    font-size: 10px; font-weight: 700; color: var(--paper);
    padding: 16px 0 6px; border-bottom: var(--bw-rule) solid var(--paper); margin-bottom: 2px;
}
#lm-conv-list { overflow-y: auto; flex: 1 1 auto; min-height: 120px; gap: 0 !important; }

/* Chats are ruled rows, like the portfolio's spreadsheet cells; the active one is a
   signal plate. No radius, no translucent hover film — the fill just changes. */
.lm-conv-row {
    gap: 0 !important; align-items: stretch !important; position: relative;
    border-bottom: var(--bw-hair) solid rgba(255, 255, 255, .22);
    flex-wrap: nowrap !important; transition: background var(--dur-1) var(--ease-snap);
}
.lm-conv-row:hover { background: var(--lm-hover); }
.lm-conv-row.lm-active { background: var(--signal); }
.lm-conv-row button {
    background: transparent !important; border: none !important; box-shadow: none !important;
    color: rgba(255, 255, 255, .8) !important; font-weight: 400 !important; font-size: 13px !important;
    justify-content: flex-start !important; text-align: left !important;
    padding: 9px 8px !important; min-height: 0 !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block !important;
    transform: none !important;
}
.lm-conv-row.lm-active button { color: var(--paper) !important; font-weight: 600 !important; }
.lm-conv-row .lm-del {
    flex: 0 0 30px !important; max-width: 30px !important; padding: 6px 0 !important;
    text-align: center !important; opacity: 0; font-size: 13px !important;
    border-left: var(--bw-hair) solid rgba(255, 255, 255, .22) !important;
    transition: opacity var(--dur-1) var(--ease-snap);
}
.lm-conv-row:hover .lm-del { opacity: .6; }
.lm-conv-row .lm-del:hover { opacity: 1; background: var(--alarm) !important; color: var(--paper) !important; }
.lm-empty { color: var(--lm-muted); font-family: var(--lm-mono); font-size: 11.5px; padding: 12px 0; }

#lm-nav { border-top: var(--bw-rule) solid var(--paper); padding-top: 10px; margin-top: 10px; gap: 0 !important; }
#lm-nav button {
    justify-content: flex-start !important; font-weight: 500 !important; font-size: 11.5px !important;
    color: rgba(255, 255, 255, .8) !important; border: none !important; background: transparent !important;
    padding: 9px 8px !important; transform: none !important; box-shadow: none !important;
}
#lm-nav button:hover { background: var(--lm-hover) !important; color: var(--paper) !important; }
#lm-nav button.lm-nav-active { background: var(--signal) !important; color: var(--paper) !important; }
.lm-kb-mini { font-family: var(--lm-mono); font-size: 10.5px; color: var(--lm-muted); padding: 10px 0 0; }

/* ================================================================ views */
#lm-views > .tab-wrapper, #lm-views > div[role="tablist"], #lm-views .tab-container { display: none !important; }
#lm-views { border: none !important; padding: 0 !important; }
#lm-views > .tabitem, #lm-views .tabitem { border: none !important; padding: 0 !important; background: transparent !important; }

/* Gradio columns are flex children; auto margins don't centre them, align-self does. */
.lm-view { max-width: 920px; width: 100%; align-self: center !important; padding: 0 20px !important; }

/* ================================================================ top bar
   A ruled row of metadata cells over the transcript — the portfolio's section
   header, doing a job: which chat, which model, what it's doing right now. */
#lm-topbar, #lm-topbar .html-container, #lm-topbar .prose { padding: 0 !important; width: 100% !important; max-width: none !important; }
.lm-topbar { padding: 16px 0 10px; width: 100%; }
.lm-cells {
    display: flex; flex-wrap: wrap; align-items: stretch;
    border-top: var(--bw-rule) solid var(--lm-line); border-bottom: var(--bw-rule) solid var(--lm-line);
}
.lm-cell {
    display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 4px 12px;
    border-right: var(--bw-rule) solid var(--lm-line); font-size: 11px; font-weight: 500;
    min-width: 0; white-space: nowrap;
}
.lm-cell:last-child { border-right: 0; }
.lm-cell-fill { background: var(--lm-on-surface); color: var(--lm-surface); font-weight: 700; }
.lm-cell-push { margin-left: auto; border-left: var(--bw-rule) solid var(--lm-line); border-right: 0; }
.lm-cell-title {
    flex: 1 1 auto; overflow: hidden;
    font-family: var(--lm-sans) !important; font-size: 15px; font-weight: 800; letter-spacing: -.015em;
    font-variation-settings: "wdth" var(--wdth-condensed); text-transform: none !important;
}
.lm-cell-title .lm-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lm-model { color: var(--lm-muted); }
.lm-muted { color: var(--lm-muted); }
.lm-spacer { flex: 1 1 auto; }

/* status: an ink plate with marching stripes under the label while a turn is in flight */
.lm-status {
    display: inline-flex; align-items: center; gap: 9px; font-size: 10.5px; font-weight: 700;
    padding: 5px 10px; background: var(--signal); color: var(--paper); animation: lm-rise var(--dur-2) var(--ease-snap);
}
.lm-status-idle { display: none; }
.lm-dot { width: 7px; height: 7px; flex: none; background: var(--paper); animation: lm-blink 1s steps(1) infinite; }

/* ================================================================ chat */
/* The chat column fills the window and the transcript takes whatever the composer plate and
   the footnote leave over, so a toolbar that wraps onto a second row shortens the transcript
   instead of pushing the footnote off the bottom of the screen. */
#lm-chat-view { height: calc(100vh - 16px) !important; }
#lm-chat-view > #lm-chatbox { height: auto !important; flex: 1 1 auto !important; min-height: 160px !important; }
#lm-chatbox .wrapper { min-height: 0 !important; }
#lm-chatbox .bubble-wrap { flex: 1 1 auto !important; min-height: 0 !important; padding-top: 4px !important; }
#lm-chatbox { border: none !important; background: transparent !important; box-shadow: none !important; }
#lm-chatbox .bubble-wrap, #lm-chatbox > div { background: transparent !important; }

/* Gradio's clear-chat trash icon wipes the view without touching saved history: remove it.
   Per-message copy buttons appear on hover only, and never on tool panels. */
#lm-chatbox .icon-button-wrapper.top-panel { display: none !important; }
#lm-chatbox .message-buttons { opacity: 0; transition: opacity var(--dur-2) ease; }
#lm-chatbox .message-row:hover + .message-buttons, #lm-chatbox .message-buttons:hover { opacity: 1; }
#lm-chatbox .message-row:has(.thought-group) + .message-buttons { display: none !important; }
#lm-chatbox .message-buttons .icon-button { border: none !important; background: transparent !important; color: var(--lm-muted) !important; }

#lm-chatbox .message-row { padding: 5px 0 !important; margin: 0 !important; }
#lm-chatbox .message { font-size: 15px !important; line-height: 1.6 !important; }

/* user: a hard plate on a signal shadow, right aligned.
   Gradio sizes each message row to its min-content width, which wraps even short messages
   word by word. Give the row the full width and cap the plate instead. */
#lm-chatbox .message-row.user-row { width: 100% !important; max-width: 100% !important; justify-content: flex-end !important; }
#lm-chatbox .user-row > .flex-wrap { flex: 0 1 auto !important; width: auto !important; max-width: 76% !important; min-width: 0 !important; }
#lm-chatbox .user-row > .flex-wrap > div, #lm-chatbox .user-row .message.user.panel-full-width { width: auto !important; }
#lm-chatbox .message.user {
    background: var(--lm-user-fill) !important; color: var(--lm-user-text) !important;
    border: var(--bw-rule) solid var(--lm-line) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--signal) !important;
    padding: 10px 15px !important; margin: 0 var(--off-1) 2px auto !important;
    width: auto !important; max-width: 100% !important; overflow-wrap: break-word;
}
#lm-chatbox .message.user * { color: var(--lm-user-text) !important; }
#lm-chatbox .user-row img { max-height: 240px; border: var(--bw-rule) solid var(--lm-line); }

/* assistant: no plate, reads like a document */
#lm-chatbox .message.bot {
    background: transparent !important; border: none !important; box-shadow: none !important;
    padding: 4px 2px !important; width: 100% !important; max-width: 100% !important;
}

/* tool + reasoning panels (Gradio renders metadata messages as .thought-group) */
#lm-chatbox .message.bot:has(.thought-group) { padding: 2px 0 !important; }
#lm-chatbox .thought-group {
    border: var(--bw-rule) solid var(--lm-line) !important;
    border-left: var(--bw-heavy) solid var(--signal) !important;
    background: var(--lm-surface) !important; padding: 7px 12px !important;
    transition: box-shadow var(--dur-1) var(--ease-snap), transform var(--dur-1) var(--ease-snap);
}
#lm-chatbox .thought-group:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow) !important; }
#lm-chatbox .thought-group .title {
    font-family: var(--lm-mono) !important; font-size: 11px !important; font-weight: 500 !important;
    letter-spacing: var(--tr-micro); text-transform: uppercase; color: var(--lm-on-surface) !important;
    display: flex; align-items: center; gap: 7px; cursor: pointer;
}
#lm-chatbox .thought-group .title p { margin: 0 !important; }
#lm-chatbox .thought-group .duration {
    font-family: var(--lm-pixel) !important; font-size: 10px !important; letter-spacing: 0;
    opacity: .8; margin-left: auto; font-variant-numeric: tabular-nums;
}
#lm-chatbox .thought-group .content {
    font-size: 13.5px !important; line-height: 1.55 !important;
    margin-top: 8px; padding-top: 8px; border-top: var(--bw-hair) solid var(--lm-line);
}

#lm-chatbox pre, #lm-chatbox code { font-family: var(--lm-mono) !important; }
#lm-chatbox pre { border: var(--bw-rule) solid var(--lm-line) !important; background: var(--lm-wash) !important; }
#lm-chatbox code { background: var(--lm-wash); padding: 1px 4px; }
#lm-chatbox pre code { background: none; padding: 0; }
#lm-chatbox a { color: var(--lm-accent-text); text-decoration: underline; text-decoration-thickness: var(--bw-rule); text-underline-offset: .18em; }
#lm-chatbox a:hover { text-decoration-thickness: var(--bw-heavy); }
#lm-chatbox table { border-collapse: collapse; font-size: 14px; }
#lm-chatbox th, #lm-chatbox td { border: var(--bw-hair) solid var(--lm-line); padding: 4px 9px; }
#lm-chatbox th { background: var(--lm-wash); font-weight: 700; }
#lm-chatbox h1, #lm-chatbox h2, #lm-chatbox h3, #lm-chatbox h4 {
    font-variation-settings: "wdth" var(--wdth-condensed); font-weight: 800; letter-spacing: -.02em;
}
#lm-chatbox blockquote { border-left: var(--bw-frame) solid var(--signal); padding-left: 12px; margin-left: 0; color: var(--lm-muted); }

/* ================================================================ empty state
   The one place the display type runs at full size: a mega headline with an
   outlined echo behind it, then the starters as plates. */
/* Gradio centres its placeholder; the headline and the starters below it share one
   left edge instead, so the panel reads as a single column. */
#lm-chatbox .placeholder { align-items: stretch !important; justify-content: flex-start !important; }
#lm-chatbox .placeholder > .md { width: 100% !important; }
.lm-hero { padding: clamp(4px, 2vh, 28px) 0 14px; animation: lm-rise .35s var(--ease-snap); position: relative; }
.lm-hero-tag {
    display: inline-flex; align-items: center; gap: 8px; font-family: var(--lm-mono);
    font-size: 10px; font-weight: 700; letter-spacing: var(--tr-micro); text-transform: uppercase;
    background: var(--lm-on-surface); color: var(--lm-surface); padding: 4px 9px; margin-bottom: 10px;
}
.lm-hero h2 { margin: 0; max-width: 15ch; }
.lm-hero h2 em { font-style: normal; color: var(--signal); }
.dark .lm-hero h2 em { color: transparent; -webkit-text-stroke: max(1.5px, .012em) var(--paper); }
.lm-hero p {
    color: var(--lm-muted); font-size: 12.5px; margin: 10px 0 0; max-width: 54ch;
    border-top: var(--bw-rule) solid var(--lm-line); padding-top: 8px;
}
.lm-hero p b { color: var(--lm-on-surface); font-weight: 700; }

#lm-chatbox .examples { max-width: 100%; margin: 0; gap: 10px !important; }
#lm-chatbox .example {
    border: var(--bw-rule) solid var(--lm-line) !important; background: var(--lm-surface) !important;
    padding: 12px 14px !important; text-align: left !important; font-size: 13.5px !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap), background var(--dur-1);
}
#lm-chatbox .example:hover {
    transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow) !important;
    background: var(--signal) !important; color: var(--paper) !important;
}
#lm-chatbox .example:active { transform: translate(var(--off-1), var(--off-1)); box-shadow: none !important; }

/* ================================================================ composer
   One square plate on a hard shadow: text box on top, model picker and tool chips
   underneath. Focus turns the frame signal and lifts the whole plate. */
#lm-composer-card {
    border: var(--bw-frame) solid var(--lm-line) !important;
    background: var(--lm-surface) !important;
    box-shadow: var(--off-2) var(--off-2) 0 0 var(--lm-shadow) !important;
    padding: 6px 10px 10px !important; gap: 0 !important; overflow: visible !important;
    margin-right: var(--off-2);
    transition: border-color var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap), transform var(--dur-1) var(--ease-snap);
}
#lm-composer-card:focus-within {
    border-color: var(--signal) !important; transform: translate(-2px, -2px);
    box-shadow: 10px 10px 0 0 var(--lm-shadow) !important;
}
#lm-composer-card > div, #lm-composer-card .styler { background: transparent !important; border: none !important; box-shadow: none !important; gap: 0 !important; }
#lm-composer { border: none !important; background: transparent !important; box-shadow: none !important; padding: 0 2px !important; }
/* MultimodalTextbox draws its own framed box inside; the plate is the frame now. */
#lm-composer div, #lm-composer label { border-color: transparent !important; box-shadow: none !important; outline: none !important; }
#lm-composer .full-container, #lm-composer .input-container { background: transparent !important; }
#lm-composer textarea {
    border: none !important; box-shadow: none !important; background: transparent !important;
    font-size: 15px !important; line-height: 1.5 !important; padding: 9px 4px !important;
}
#lm-composer textarea::placeholder { color: var(--lm-muted); }
#lm-composer button.submit-button, #lm-composer .submit-button {
    background: var(--signal) !important; color: var(--paper) !important;
    border: var(--bw-rule) solid var(--lm-line) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap);
}
#lm-composer .submit-button:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow) !important; }
#lm-composer .submit-button:active { transform: translate(var(--off-1), var(--off-1)); box-shadow: none !important; }
#lm-composer .stop-button {
    background: var(--alarm) !important; color: var(--paper) !important;
    border: var(--bw-rule) solid var(--lm-line) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
}
#lm-composer .upload-button { color: var(--lm-on-surface) !important; border: var(--bw-rule) solid transparent !important; }
#lm-composer .upload-button:hover { border-color: var(--lm-line) !important; }

#lm-toolbar {
    gap: 6px !important; align-items: center !important; flex-wrap: wrap !important;
    padding: 8px 2px 0 !important; margin-top: 6px !important; background: transparent !important;
    border-top: var(--bw-hair) solid var(--lm-line) !important;
}
#lm-toolbar > * { flex: 0 0 auto !important; min-width: 0 !important; }

/* pickers: ruled cells, not form fields */
#lm-model-picker, #lm-model-picker > div, #lm-model-picker label,
#lm-kv-picker, #lm-kv-picker > div, #lm-kv-picker label,
#lm-scope-picker, #lm-scope-picker > div, #lm-scope-picker label {
    width: auto !important; padding: 0 !important; margin: 0 !important;
    background: transparent !important; border: none !important; box-shadow: none !important; min-height: 0 !important;
}
#lm-model-picker .wrap-inner, #lm-model-picker .secondary-wrap, #lm-model-picker input,
#lm-kv-picker .wrap-inner, #lm-kv-picker .secondary-wrap, #lm-kv-picker input,
#lm-scope-picker .wrap-inner, #lm-scope-picker .secondary-wrap, #lm-scope-picker input {
    background: transparent !important; border: none !important; box-shadow: none !important;
}
#lm-model-picker .wrap, #lm-kv-picker .wrap, #lm-scope-picker .wrap {
    border: var(--bw-rule) solid var(--lm-line) !important;
    padding: 0 8px 0 10px !important; min-height: 30px !important; height: 30px !important;
    transition: background var(--dur-1) var(--ease-snap), color var(--dur-1);
}
#lm-model-picker .wrap:hover, #lm-kv-picker .wrap:hover, #lm-scope-picker .wrap:hover { background: var(--lm-wash) !important; }
#lm-model-picker input, #lm-kv-picker input, #lm-scope-picker input {
    font-family: var(--lm-mono) !important; font-size: 11px !important; font-weight: 700 !important;
    letter-spacing: var(--tr-micro); text-transform: uppercase; cursor: pointer;
    padding: 0 !important; height: 26px !important; text-overflow: ellipsis;
}
#lm-model-picker input { width: 22ch !important; }
#lm-kv-picker input { width: 17ch !important; color: var(--lm-muted) !important; }
#lm-scope-picker input { width: 15ch !important; color: var(--lm-muted) !important; }
#lm-model-picker ul.options, #lm-kv-picker ul.options, #lm-scope-picker ul.options {
    border: var(--bw-frame) solid var(--lm-line) !important; background: var(--lm-surface) !important;
    box-shadow: var(--off-2) var(--off-2) 0 0 var(--lm-shadow) !important;
    font-family: var(--lm-mono); font-size: 12px; min-width: 230px; padding: 0 !important;
}
#lm-model-picker ul.options li, #lm-kv-picker ul.options li, #lm-scope-picker ul.options li { padding: 7px 10px !important; }
#lm-model-picker ul.options li.selected, #lm-model-picker ul.options li:hover,
#lm-kv-picker ul.options li.selected, #lm-kv-picker ul.options li:hover,
#lm-scope-picker ul.options li.selected, #lm-scope-picker ul.options li:hover {
    background: var(--signal) !important; color: var(--paper) !important;
}

/* tool chips: off is a ruled cell, on is a signal plate */
.lm-chip {
    display: inline-flex !important; align-items: center; gap: 7px;
    border: var(--bw-rule) solid var(--lm-line) !important; background: transparent !important;
    color: var(--lm-on-surface) !important; font-size: 10.5px !important; font-weight: 700 !important;
    padding: 5px 11px 5px 9px !important; min-height: 30px !important; box-shadow: none !important;
    transition: background var(--dur-1) var(--ease-snap), color var(--dur-1), transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap);
}
.lm-chip::before {
    content: ""; width: 14px; height: 14px; flex: 0 0 14px; background-color: currentColor;
    -webkit-mask: var(--lm-icon) center / contain no-repeat; mask: var(--lm-icon) center / contain no-repeat;
}
.lm-chip:hover { background: var(--lm-wash) !important; }
.lm-chip.lm-chip-on {
    background: var(--signal) !important; border-color: var(--lm-line) !important; color: var(--paper) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
}
.lm-chip.lm-chip-on:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow) !important; }
.lm-chip.lm-chip-locked { cursor: default; }
.lm-chip.lm-chip-disabled { opacity: .4; cursor: not-allowed; }
#lm-export { --lm-icon: var(--icon-download); margin-left: auto !important; }
#lm-chip-web { --lm-icon: var(--icon-globe); }
#lm-chip-kb { --lm-icon: var(--icon-book); }
#lm-chip-think { --lm-icon: var(--icon-spark); }
#lm-chip-voice { --lm-icon: var(--icon-mic); }
/* Hidden download target: the PDF button builds the file, then clicks this programmatically. */
#lm-export-file, #lm-export-file * { position: absolute !important; width: 1px !important; height: 1px !important; opacity: 0 !important; pointer-events: none !important; overflow: hidden !important; }

/* a chat still answering in the background */
.lm-conv-row.lm-busy > button:first-child { padding-right: 22px !important; }
.lm-conv-row.lm-busy::after {
    content: ""; position: absolute; right: 38px; top: 50%; width: 6px; height: 6px; margin-top: -3px;
    background: var(--signal); animation: lm-blink 1s steps(1) infinite; pointer-events: none;
}
.lm-conv-row.lm-active.lm-busy::after { background: var(--paper); }

/* ================================================================ voice
   A status strip above the composer while Voice is on. The meter bars are hard
   blocks that step, never fade. */
#lm-voice-bar {
    display: flex; align-items: center; gap: 10px; align-self: center; width: fit-content !important;
    margin: 0 auto 8px; padding: 6px 8px 6px 12px;
    background: var(--lm-surface); border: var(--bw-rule) solid var(--lm-line);
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow);
    font-family: var(--lm-mono); font-size: 11px; letter-spacing: var(--tr-micro); text-transform: uppercase;
    color: var(--lm-on-surface); max-width: 100%;
}
#lm-voice-bar[hidden] { display: none !important; }
#lm-voice-bar .lm-vb-label { min-width: 0; overflow-wrap: anywhere; }
#lm-voice-bar .lm-vb-meter { display: inline-flex; align-items: center; gap: 3px; height: 18px; flex: none; }
#lm-voice-bar .lm-vb-meter i {
    display: block; width: 4px; height: 18px; background: var(--signal);
    transform: scaleY(.15); transition: transform 60ms linear;
}
#lm-voice-bar.lm-vb-starting .lm-vb-meter i, #lm-voice-bar.lm-vb-transcribing .lm-vb-meter i,
#lm-voice-bar.lm-vb-waiting .lm-vb-meter i { animation: lm-vb-wait 1.2s steps(2) infinite; transition: none; }
#lm-voice-bar.lm-vb-speaking .lm-vb-meter i { animation: lm-vb-talk .9s steps(2) infinite; transition: none; background: var(--lm-on-surface); }
#lm-voice-bar .lm-vb-meter i:nth-child(2) { animation-delay: .12s; }
#lm-voice-bar .lm-vb-meter i:nth-child(3) { animation-delay: .24s; }
#lm-voice-bar .lm-vb-meter i:nth-child(4) { animation-delay: .36s; }
#lm-voice-bar .lm-vb-meter i:nth-child(5) { animation-delay: .48s; }
#lm-voice-bar.lm-vb-error { border-color: var(--alarm); box-shadow: var(--off-1) var(--off-1) 0 0 var(--alarm); }
#lm-voice-bar.lm-vb-error .lm-vb-meter { display: none; }
#lm-voice-bar .lm-vb-action {
    flex: none; border: var(--bw-rule) solid var(--lm-line); background: transparent; color: inherit;
    padding: 4px 11px; font: inherit; font-weight: 700; cursor: pointer;
    transition: background var(--dur-1), color var(--dur-1);
}
#lm-voice-bar .lm-vb-action:hover { background: var(--signal); color: var(--paper); }
#lm-voice-bar .lm-vb-action[hidden] { display: none; }
@keyframes lm-vb-wait { 0%, 100% { transform: scaleY(.2); } 50% { transform: scaleY(.5); } }
@keyframes lm-vb-talk { 0%, 100% { transform: scaleY(.3); } 50% { transform: scaleY(1); } }
@media (prefers-reduced-motion: reduce) {
    #lm-voice-bar .lm-vb-meter i, .lm-hazard, .lm-dot, .lm-conv-row.lm-busy::after { animation: none !important; }
}

/* ================================================================ badges + HUD */
.lm-badge {
    display: inline-block; font-size: 9.5px; font-weight: 700; padding: 2px 5px; vertical-align: 1px;
    border: var(--bw-hair) solid var(--lm-line); color: var(--lm-on-surface);
}
.lm-badge-cloud { background: var(--signal); border-color: var(--signal); color: var(--paper); }

/* status HUD: a ruled readout fixed to the top right, numerals in the pixel face */
#lm-hud { position: fixed !important; top: 0; right: 0; z-index: 60; width: auto !important; padding: 0 !important; background: transparent !important; border: none !important; }
#lm-hud .html-container, #lm-hud .prose { padding: 0 !important; }
.lm-hud {
    display: flex; align-items: stretch;
    background: var(--lm-surface); border: var(--bw-rule) solid var(--lm-line); border-top: 0; border-right: 0;
}
.lm-hud-pill {
    display: inline-flex; align-items: center; gap: 7px; font-size: 10px; font-weight: 500;
    padding: 7px 11px; white-space: nowrap; color: var(--lm-on-surface);
    border-right: var(--bw-hair) solid var(--lm-line);
}
.lm-hud-pill:last-child { border-right: 0; }
.lm-hud-pill b { font-weight: 700; color: var(--lm-muted); font-size: 9.5px; }
.lm-hud-pill .lm-num { font-size: 10px; }
.lm-meter { display: inline-block; width: 36px; height: 7px; background: var(--lm-wash); border: var(--bw-hair) solid var(--lm-line); overflow: hidden; }
.lm-meter > i { display: block; height: 100%; background: var(--signal); transition: width .4s var(--ease-snap); }
.lm-hud-warm { background: var(--lm-on-surface); color: var(--lm-surface); }
.lm-hud-warm b { color: var(--lm-surface); opacity: .75; }
.lm-hud-warm .lm-meter { background: transparent; border-color: var(--lm-surface); }
.lm-hud-warm .lm-meter > i { background: var(--lm-surface); }
.lm-hud-hot { background: var(--alarm); color: var(--paper); }
.lm-hud-hot b { color: var(--paper); opacity: .8; }
.lm-hud-hot .lm-meter { background: transparent; border-color: var(--paper); }
.lm-hud-hot .lm-meter > i { background: var(--paper); }
/* While the readout is pinned to the corner, every view starts below it, so nothing is
   ever hidden underneath. Narrower than that, it stops being fixed and joins the flow. */
@media (min-width: 1101px) {
    .lm-view { padding-top: 36px !important; }
}
@media (max-width: 1100px) {
    #lm-hud { position: static !important; }
    .lm-hud { border: var(--bw-rule) solid var(--lm-line); border-top: 0; flex-wrap: wrap; justify-content: flex-end; }
}

.lm-footnote {
    font-size: 10px; color: var(--lm-muted); padding: 10px 0 14px;
    border-top: var(--bw-hair) solid var(--lm-line); margin-top: 10px;
}
.lm-footnote-cloud { color: var(--lm-on-surface); border-top-color: var(--alarm); border-top-width: var(--bw-rule); }
.lm-footnote-cloud b { color: var(--alarm); font-weight: 700; }
.dark .lm-footnote-cloud b { color: var(--paper); background: var(--alarm); padding: 1px 4px; }

/* ================================================================ knowledge, search, tasks, tools */
.lm-page-head { padding: 26px 0 16px; }
.lm-page-head h2 {
    font-family: var(--lm-sans); font-weight: 900; font-variation-settings: "wdth" var(--wdth-condensed);
    font-size: clamp(1.75rem, 1.1rem + 2.2vw, 3rem); line-height: .92; letter-spacing: -.03em;
    text-transform: uppercase; margin: 0 0 10px;
}
.lm-page-head p {
    color: var(--lm-muted); margin: 0; font-size: 13.5px; max-width: 62ch;
    border-top: var(--bw-rule) solid var(--lm-line); padding-top: 10px;
}
.lm-card {
    border: var(--bw-frame) solid var(--lm-line) !important; background: var(--lm-surface) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
    padding: 16px !important; margin-right: var(--off-1) !important;
}
.lm-card-title {
    font-weight: 700; font-size: 10.5px; margin-bottom: 10px; padding-bottom: 6px;
    border-bottom: var(--bw-rule) solid var(--lm-line); color: var(--lm-on-surface);
}
.lm-stats { display: flex; flex-wrap: wrap; border: var(--bw-rule) solid var(--lm-line); margin-top: 14px; }
.lm-stat {
    display: inline-flex; gap: 8px; align-items: baseline; padding: 8px 14px;
    font-family: var(--lm-mono); font-size: 10px; letter-spacing: var(--tr-micro); text-transform: uppercase;
    color: var(--lm-muted); border-right: var(--bw-rule) solid var(--lm-line);
}
.lm-stat:last-child { border-right: 0; }
.lm-stat b { font-family: var(--lm-pixel); font-size: 17px; letter-spacing: 0; color: var(--lm-on-surface); font-weight: 400; }

#lm-sources td, #lm-sources th, #lm-sources td *, #lm-sources th * {
    font-family: var(--lm-sans) !important; font-size: 13px !important; overflow-wrap: anywhere; word-break: normal;
}
#lm-sources th, #lm-sources th * {
    font-family: var(--lm-mono) !important; font-size: 10px !important; font-weight: 700 !important;
    letter-spacing: var(--tr-micro); text-transform: uppercase;
}
#lm-sources tr { cursor: pointer; }
#lm-sources tbody tr:hover td { background: var(--lm-wash) !important; }
#lm-sources table { border: var(--bw-rule) solid var(--lm-line) !important; }

#lm-search-input, #lm-search-input > label, #lm-search-input .wrap { background: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; }
#lm-search-input textarea, #lm-search-input input {
    border: var(--bw-frame) solid var(--lm-line) !important; background: var(--lm-surface) !important;
    box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
    padding: 12px 14px !important; font-size: 15px !important;
}
#lm-search-input textarea:focus, #lm-search-input input:focus { border-color: var(--signal) !important; }

.lm-sections { display: flex; flex-direction: column; font-size: 13px; margin-bottom: 10px; border-top: var(--bw-hair) solid var(--lm-line); }
.lm-section-row { display: flex; align-items: center; gap: 8px; padding: 7px 2px; border-bottom: var(--bw-hair) solid var(--lm-line); }
.lm-section-row .lm-muted { margin-left: auto; font-family: var(--lm-mono); font-size: 10px; letter-spacing: var(--tr-micro); text-transform: uppercase; }

.lm-batch { border: var(--bw-rule) solid var(--lm-line); padding: 10px 12px; margin-bottom: 10px; }
.lm-batch-head {
    display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
    margin-bottom: 8px; padding-bottom: 6px; border-bottom: var(--bw-hair) solid var(--lm-line);
    font-family: var(--lm-mono); font-size: 10.5px; letter-spacing: var(--tr-micro); text-transform: uppercase;
}
.lm-task { display: flex; gap: 9px; align-items: baseline; font-size: 13px; padding: 3px 0; }
.lm-task-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lm-task-error {
    font-family: var(--lm-mono); font-size: 11px; color: var(--paper); background: var(--alarm);
    padding: 3px 7px; margin: 2px 0 6px 26px;
}
.lm-request {
    border: var(--bw-rule) solid var(--signal); border-left-width: var(--bw-heavy);
    padding: 9px 11px; margin-bottom: 8px; font-size: 13px;
}
.lm-request code { font-size: 11.5px; overflow-wrap: anywhere; background: var(--lm-wash); padding: 1px 4px; }

.hit-card {
    border: var(--bw-rule) solid var(--lm-line); border-left: var(--bw-heavy) solid var(--signal);
    padding: 12px 15px; margin-bottom: 10px; background: var(--lm-surface);
    animation: lm-rise var(--dur-2) var(--ease-snap);
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap);
}
.hit-card:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow); }
.hit-card .hit-meta {
    font-family: var(--lm-mono); font-size: 10px; letter-spacing: var(--tr-micro); text-transform: uppercase;
    color: var(--lm-muted); margin-bottom: 7px; padding-bottom: 5px; border-bottom: var(--bw-hair) solid var(--lm-line);
}
.hit-card .hit-text { font-size: 14px; line-height: 1.55; white-space: pre-wrap; }
.hit-score { float: right; font-family: var(--lm-pixel); letter-spacing: 0; color: var(--lm-on-surface); }

/* Gradio's own buttons outside the chat view (upload, remove, run a batch) get the
   same plate-and-press treatment, so nothing in the app reads as a default widget. */
#lm-upload-section button, #lm-search-row button, .lm-card button:not(.lm-chip) {
    border: var(--bw-rule) solid var(--lm-line) !important; font-family: var(--lm-mono) !important;
    font-size: 10.5px !important; font-weight: 700 !important; letter-spacing: var(--tr-micro);
    text-transform: uppercase; box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important;
    transition: transform var(--dur-1) var(--ease-snap), box-shadow var(--dur-1) var(--ease-snap);
}
#lm-upload-section button:hover, #lm-search-row button:hover, .lm-card button:not(.lm-chip):hover {
    transform: translate(-2px, -2px); box-shadow: 6px 6px 0 0 var(--lm-shadow) !important;
}
#lm-upload-section button:active, #lm-search-row button:active, .lm-card button:not(.lm-chip):active {
    transform: translate(var(--off-1), var(--off-1)); box-shadow: none !important;
}
.lm-card textarea, .lm-card input[type="text"] { border: var(--bw-rule) solid var(--lm-line) !important; }
.lm-card label span, .lm-card .block > label > span {
    font-family: var(--lm-mono) !important; font-size: 10px !important; font-weight: 700 !important;
    letter-spacing: var(--tr-micro); text-transform: uppercase;
}

/* ================================================================ narrow screens */
@media (max-width: 760px) {
    /* The page wrapper's own 32px gutters are trimmed from JS (see PAGE_GUTTER_CSS):
       Gradio scopes this stylesheet under .contain, which sits below that element. */
    .lm-view { padding: 0 8px !important; }
    .lm-hero { padding-top: 2vh; }
    .lm-cell-title { font-size: 14px; }
    .lm-cells { flex-wrap: wrap; }
    .lm-cell-push { margin-left: 0; flex-basis: 100%; border-left: 0; border-top: var(--bw-rule) solid var(--lm-line); }
    #lm-composer-card, .lm-card { margin-right: 0 !important; box-shadow: var(--off-1) var(--off-1) 0 0 var(--lm-shadow) !important; }
    /* Compact the toolbar so the controls sit two or three to a row rather than one
       each, which otherwise leaves the transcript a sliver of the screen. */
    #lm-toolbar { gap: 4px !important; }
    .lm-chip { font-size: 9.5px !important; padding: 4px 8px 4px 7px !important; min-height: 28px !important; gap: 5px; }
    .lm-chip::before { width: 12px; height: 12px; flex-basis: 12px; }
    #lm-model-picker .wrap, #lm-kv-picker .wrap, #lm-scope-picker .wrap {
        min-height: 28px !important; height: 28px !important; padding: 0 6px 0 8px !important;
    }
    #lm-model-picker input, #lm-kv-picker input, #lm-scope-picker input { font-size: 9.5px !important; height: 24px !important; }
    #lm-model-picker input { width: 14ch !important; }
    #lm-kv-picker input { width: 11ch !important; }
    #lm-scope-picker input { width: 10ch !important; }
}
"""
