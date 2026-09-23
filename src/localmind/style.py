"""House style: British English, and none of the tells that mark text as machine-written.

Two parts. A writing guide for the system prompt, built from Wikipedia's "Signs of AI writing"
catalogue. And a deterministic spelling pass that turns American spellings into British ones in
the prose of an answer. The pass never touches code, URLs, LaTeX commands or proper nouns, since
`\\color`, `https://…/center` and "Kennedy Center" must stay exactly as they are.
"""
from __future__ import annotations

import re

STYLE_GUIDE = """

WRITING STYLE (every answer, and anything you write for the user such as a CV or cover letter):
- British English throughout: colour, organise, analyse, centre, travelled, programme (but a
  computer program), licence (noun), practise (verb), cheque. Dates as 19 September 2026.
- Write plainly and specifically, like a careful human writer. Say what a thing is ("X is a
  bank"), not "X serves as / stands as / represents / boasts a".
- Never use these words: delve, tapestry, testament, pivotal, crucial, vibrant, intricate,
  meticulous, showcase, underscore, foster, garner, bolster, enduring, landscape (unless it's
  scenery), realm, embark, seamless, leverage (as a verb), robust (unless technical), nestled,
  groundbreaking, renowned, "rich heritage", "diverse array", "plays a vital role", "valuable
  insights", "in today's fast-paced world".
- No puffery or significance-inflation: don't claim something "highlights the importance of",
  "reflects broader trends", "sets the stage for" or "leaves a lasting legacy".
- No negative parallelisms ("it's not just X, it's Y", "not only... but also") and don't group
  things in threes by reflex. No vague attributions ("experts say", "observers note"): name the
  source or leave it out.
- No formulaic endings: no "In conclusion", "Overall", "Despite these challenges...", "Future
  outlook", and no closing offers ("I hope this helps", "Let me know if..."). No openers like
  "Certainly!", "Great question" or "Absolutely".
- Formatting only when it helps: few headings (sentence case, never title case), bold rarely,
  no emoji, no horizontal rules, em dashes sparingly (prefer commas, colons or full stops).
- For CVs and applications: concrete achievements with numbers, active verbs, no clichés
  ("results-driven", "passionate about", "proven track record", "team player").
"""

# American -> British. Deliberately a curated list: words whose British form is always right in
# prose. Ambiguous ones (program, license, practice, meter, check, tire, dialog) are left alone.
_BASE = {
    "color": "colour", "favor": "favour", "favorite": "favourite", "flavor": "flavour",
    "honor": "honour", "humor": "humour", "labor": "labour", "neighbor": "neighbour",
    "behavior": "behaviour", "rumor": "rumour", "vapor": "vapour", "savior": "saviour",
    "endeavor": "endeavour", "harbor": "harbour", "armor": "armour", "odor": "odour",
    "center": "centre", "theater": "theatre", "fiber": "fibre", "caliber": "calibre",
    "somber": "sombre", "defense": "defence", "offense": "offence", "pretense": "pretence",
    "catalog": "catalogue", "analog": "analogue", "gray": "grey", "aluminum": "aluminium",
    "jewelry": "jewellery", "cozy": "cosy", "mold": "mould", "plow": "plough",
    "fulfill": "fulfil", "enrollment": "enrolment", "skillful": "skilful", "willful": "wilful",
    "installment": "instalment", "judgment": "judgement", "aging": "ageing",
    "maneuver": "manoeuvre", "pediatric": "paediatric", "anemia": "anaemia",
    "estrogen": "oestrogen", "esophagus": "oesophagus", "tumor": "tumour",
}
# -ize/-yze verbs (and their families) that British English writes with -ise/-yse.
_ISE = (
    "organ real recogn priorit optim summar special emphas minim maxim util custom final "
    "standard apolog critic categor visual character capital modern author memor normal "
    "synchron initial monet central global local ideal symbol mobil stabil harmon energ "
    "legal neutral econom famil scrutin sympath theor jeopard patron fertil hospital "
    "commercial industrial rational revolution digit sanit token"
).split()
_YSE = ("anal", "paral", "catal", "dial")
_DOUBLE_L = ("travel", "cancel", "model", "label", "level", "fuel", "signal", "channel",
             "counsel", "equal", "marvel", "total", "tunnel", "quarrel", "jewel", "dial", "shovel")


def _build() -> dict[str, str]:
    words: dict[str, str] = {}
    for us, uk in _BASE.items():
        words[us] = uk
        for suffix in ("s", "ed", "ing", "ful", "less", "able", "ist", "ists", "ation", "ations"):
            words.setdefault(us + suffix, uk + suffix)
    words.update({"colorful": "colourful", "honorable": "honourable", "favorable": "favourable",
                  "favored": "favoured", "centered": "centred", "centering": "centring",
                  "fulfillment": "fulfilment", "fulfilled": "fulfilled", "fulfilling": "fulfilling",
                  "defenses": "defences", "offenses": "offences", "neighborhood": "neighbourhood",
                  "neighborhoods": "neighbourhoods", "behavioral": "behavioural", "laborious": "laborious",
                  "humorous": "humorous", "honorary": "honorary", "coloration": "colouration"})
    for stem in _ISE:
        for us_end, uk_end in (("ize", "ise"), ("izes", "ises"), ("ized", "ised"), ("izing", "ising"),
                               ("ization", "isation"), ("izations", "isations"), ("izer", "iser"), ("izers", "isers")):
            words[stem + us_end] = stem + uk_end
    for stem in _YSE:
        for us_end, uk_end in (("yze", "yse"), ("yzes", "yses"), ("yzed", "ysed"), ("yzing", "ysing"), ("yzer", "yser")):
            words[stem + us_end] = stem + uk_end
    for stem in _DOUBLE_L:
        for suffix in ("ed", "ing", "er", "ers"):
            words[stem + suffix] = stem + "l" + suffix
    return words


US_TO_UK = _build()
_WORD = re.compile(r"(?<![\\\w@/.#-])([A-Za-z]+)(?![\w/@])")
# Stretches never touched: fenced and inline code, URLs, markdown link targets, LaTeX commands
# with their first argument (\begin{center}, \color{red}), and e-mail addresses.
_PROTECTED = re.compile(
    r"```.*?(?:```|$)|`[^`\n]*`|https?://\S+|www\.\S+|\]\([^)]*\)|\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?|\S+@\S+\.\w+",
    re.S,
)
# What may come just before a capitalised word at the start of a sentence, heading or list item.
_STARTS_AFTER = re.compile(r"(^|[.!?:\n#*>]|\n\s*(?:[-*•]|\d+[.)]))$")


def british(text: str) -> str:
    """American spellings in prose become British; everything else is left byte-for-byte."""
    if not text:
        return text
    out, last = [], 0
    for protected in _PROTECTED.finditer(text):
        out.append(_convert(text[last:protected.start()], text[:protected.start()]))
        out.append(protected.group(0))
        last = protected.end()
    out.append(_convert(text[last:], text[:last]))
    return "".join(out)


def _convert(chunk: str, before: str) -> str:
    def swap(match: re.Match) -> str:
        word = match.group(1)
        lower = word.lower()
        uk = US_TO_UK.get(lower)
        if uk is None:
            return word
        if word == lower:
            return uk
        if word == word.upper() and len(word) > 1:
            return uk.upper()
        if word == word.capitalize():
            # A capital mid-sentence is usually a name ("Kennedy Center", "Color Run"): leave it.
            preceding = (before + chunk[: match.start()]).rstrip(" \t")
            if _STARTS_AFTER.search(preceding[-12:]):
                return uk.capitalize()
        return word

    return _WORD.sub(swap, chunk)


# Words from the guide's ban list, for spotting drift in tests and logs.
AI_TELLS = re.compile(
    r"\b(delve[sd]?|delving|tapestry|testament|pivotal|vibrant|intricate|meticulous(?:ly)?|showcas(?:e|es|ed|ing)|"
    r"underscor(?:e|es|ed|ing)|foster(?:s|ed|ing)?|garner(?:s|ed)?|bolster(?:s|ed)?|nestled|groundbreaking|"
    r"serves as|stands as|plays a (?:vital|crucial|pivotal) role|in conclusion|i hope this helps)\b",
    re.I,
)


def ai_tells(text: str) -> list[str]:
    return [m.group(0).lower() for m in AI_TELLS.finditer(text or "")]
