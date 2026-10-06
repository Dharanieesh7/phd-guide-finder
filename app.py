# The web page. Start it with:   streamlit run app.py
#
# Design: "the reading-room index". The page reads like the index of a printed journal:
# one search sentence, one honest summary line, and one ruled entry per researcher.
# Green means only one thing: "this researcher says they are taking students".
# Colours, fonts and spacing live in tokens.css; the page styles live in app.css.
#
# Saved searches (the demo/ folder) open free. A new search runs live through SerpApi
# (key from .env, or typed into the page): Quick = about 7 searches, Thorough = about 11-13.
import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlparse

import streamlit as st

import finder
from make_demo import file_name
from serp import UNKNOWN_LEFT, env_key, searches_left

FOLDER = Path(__file__).parent
DEMO = FOLDER / "demo"
THIN_SUBJECT = 15        # fewer Scholar-page authors than this in the topic papers = warn the student
DEPTHS = ["Quick · about 7 searches", "Thorough · about 11–13 searches"]
ANYWHERE = "any country"
COUNTRIES = [ANYWHERE, "India", "Singapore", "USA", "UK", "Germany", "Canada", "Australia",
             "Hong Kong", "China", "Japan", "Korea", "Netherlands", "Switzerland", "France", "Sweden"]
STUDENT_PLACES = {"PhD", "Master's", "Research assistant", "Not specified"}
EXAMPLE = ("natural language processing", "India")     # shown on a first visit
GITHUB = "https://github.com/Dharanieesh7/phd-guide-finder"

st.set_page_config(page_title="PhD Guide Finder", page_icon=":material/menu_book:", layout="centered")


# ---------------- small helpers ----------------

def esc(text):
    """Everything that came from the web is escaped before it goes into the page."""
    return html.escape(str(text if text is not None else ""), quote=True)


def safe_url(url):
    """Only real web links (http/https) become clickable."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return ""
    return esc(url) if parsed.scheme in ("http", "https") and parsed.netloc else ""


def put(markup):
    st.html(markup)


def nice_date(iso):
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.day} {d.strftime('%b %Y')}"


def searches_left_for(key):
    """Searches left on this key (free check). Remembered for this tab so the page stays fast."""
    tag = hashlib.sha256(key.encode()).hexdigest()
    remembered = st.session_state.get("left")
    if not remembered or remembered[0] != tag or remembered[1] == UNKNOWN_LEFT:   # ask again after a hiccup
        st.session_state["left"] = (tag, searches_left(key))
    return st.session_state["left"][1]


def hide_key(message, key):
    """Error messages can contain the request address, which includes the key. Never show it."""
    message = re.sub(r"api_key=[^&\s]+", "api_key=•••", message)
    return message.replace(key, "•••") if key else message


def saved_searches():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DEMO.glob("*.json"))]


def load_saved(topic, country):
    path = DEMO / file_name(topic, country)
    return json.loads(path.read_text(encoding="utf-8")) if topic and path.exists() else None


def search_link(topic, country):
    label = f"{topic}, {country}" if country else topic
    return f'<a href="?{esc(urlencode({"q": topic, "in": country or ""}))}" target="_self">{esc(label)}</a>'


def taking_students(p):
    return p["hiring"] == "Says so" and bool(STUDENT_PLACES & set(p.get("offers", [])))


# ---------------- one researcher = one index entry ----------------

def status_html(p):
    proof = f' — <q>{esc(p["proof"])}</q>' if p.get("proof") else ""
    if p["hiring"] == "Says so":
        if taking_students(p):
            named = [o for o in p["offers"] if o in STUDENT_PLACES and o != "Not specified"]
            label = "Taking " + ", ".join(named) if named else "Has open positions"
            return (f'<p class="entry__status"><span aria-hidden="true" class="sq sq--go"></span>'
                    f'<span class="go">{esc(label)}</span>{proof}</p>')
        return (f'<p class="entry__status"><span aria-hidden="true" class="sq sq--part"></span>'
                f'Openings for {esc(", ".join(p["offers"]))} — not PhD{proof}</p>')
    reason = {"Not mentioned": "Not mentioned on their homepage",
              "Homepage would not open": "Couldn't read their homepage"}.get(p["hiring"], "No homepage listed")
    return f'<p class="entry__status"><span aria-hidden="true" class="sq sq--off"></span>{reason} — email them to ask</p>'


def entry_html(rank, p):
    where = [p["job"] or p["role"]]
    if p["country"] != "Not sure" and p["country"].lower() not in (p["job"] or "").lower():
        where.append(p["country"])
    role_note = f' {esc(p["role_note"])}' if p.get("role_note") else ""
    subjects = " · ".join(esc(s) for s in p["subjects"][:4])
    papers = ""
    for paper in p["papers"]:
        link = safe_url(paper.get("link"))
        title = esc(paper.get("title"))
        title = f'<a href="{link}" target="_blank" rel="noopener">{title}</a>' if link else title
        papers += f'<li><span class="yr">{esc(paper.get("year"))}</span>{title}</li>'
    papers = (f'<ul class="papers">{papers}</ul>' if papers
              else '<p class="entry__line">No recent paper titles matched the topic closely.</p>')
    links = []
    if safe_url(p.get("scholar_link")):
        links.append(f'<a href="{safe_url(p["scholar_link"])}" target="_blank" rel="noopener">Scholar →</a>')
    if safe_url(p.get("homepage")):
        links.append(f'<a href="{safe_url(p["homepage"])}" target="_blank" rel="noopener">Homepage →</a>')
    h_index = p["h_index"] if p["h_index"] is not None else "—"
    return (
        f'<article class="entry"><div class="entry__rank">{rank}</div><div class="entry__main">'
        f'<h3 class="entry__name">{esc(p["name"])}</h3>'
        f'<p class="entry__where">{" · ".join(esc(w) for w in where)}{role_note}</p>'
        f'{status_html(p)}'
        + (f'<p class="entry__line"><b>Works on</b> {subjects}</p>' if subjects else "")
        + f'<details class="entry__more"><summary>Recent papers and how we found them</summary>{papers}'
        f'<p class="entry__line"><b>Found by</b> {esc(p["found_via"])} · on topic because of '
        f'{esc(p["topic_reason"])}</p></details></div>'
        f'<div class="entry__aside"><span class="entry__h">{esc(h_index)}</span>h-index{"".join(links)}</div>'
        f'</article>'
    )


# ---------------- the rest of a result ----------------

def summary_html(result, how):
    here, stats = result["here"], result["stats"]
    n, taking = len(here), sum(taking_students(p) for p in here)
    topic = esc(result["topic"])
    where = f"in {esc(result['country'])}" if result["country"] else "worldwide"
    if n:
        text = f'<b>{n}</b> researcher{"s" if n != 1 else ""} {where} {"are" if n != 1 else "is"} actively working on {topic}.'
        if taking:
            text += f' <span class="go"><b>{taking}</b> {"says" if taking == 1 else "say"} they\'re taking students.</span>'
        else:
            text += " None of them says so on their homepage — that doesn't mean no, so email to ask."
    else:
        text = f"Nobody {where} working on {topic} turned up in this search."
    text += (f' We read <b>{stats["opened"]}</b> Google Scholar profiles and left out <b>{stats["off_topic"]}</b>'
             f' that weren\'t really on this topic.')
    notes = {
        "example": "Example: a saved search, opened free. Type your own topic above.",
        "saved": f"Saved search from {nice_date(result.get('searched_on'))} — opened free, no searches used. "
                 "Tick “Search again” for fresh results.",
        "live": f"Searched live just now through SerpApi — {stats.get('new_searches', '?')} searches used.",
    }
    out = f'<p class="summary">{text}</p><p class="note">{notes.get(how, "")}</p>'
    if stats.get("scholar_authors", 99) < THIN_SUBJECT:
        out += ('<p class="note">Few researchers in this subject have Google Scholar pages (common in literature, '
                'languages and some law topics), so this list may be short. Also check university department pages.</p>')
    if not n:
        out += '<p class="note">Try a broader topic, or search in any country.</p>'
    elif n <= 2 and stats["off_topic"] >= 8:
        # Seen with "machine learning" in India: most papers came from people in other fields using it.
        out += ('<p class="note">Very broad topics match many papers by people from other fields who just use the '
                'method. A more specific topic usually finds more guides — for example “speech recognition” '
                'instead of “machine learning”.</p>')
    return out


def also_html(result):
    rows = ""
    for p in result["elsewhere"]:
        link = safe_url(p.get("scholar_link"))
        name = f'<a href="{link}" target="_blank" rel="noopener">{esc(p["name"])}</a>' if link else esc(p["name"])
        rows += f'<li>{name} — {esc(p["job"] or p["role"])} · {esc(p["country"])} · h-index {esc(p["h_index"])}</li>'
    return (f'<h2 class="section-title">Also strong on this topic, outside {esc(result["country"])}</h2>'
            f'<ul class="also">{rows}</ul>')


def method_html(result):
    rows = "".join(
        f'<tr><td>{esc(t["name"])}</td><td>{esc(t["found_via"])}</td>'
        f'<td>{"yes" if t["on_topic"] else "no"}</td><td>{"yes" if t["in_country"] else "no"}</td></tr>'
        for t in result["trail"])
    return (
        '<details class="method"><summary>How this search worked</summary><ol>'
        '<li><b>Google Scholar API (SerpApi)</b> finds recent, well-cited papers on the topic.</li>'
        '<li><b>Google Scholar Author API (SerpApi)</b> opens the profiles of the strongest authors.</li>'
        '<li><b>Co-authors</b>: every profile lists who the person publishes with. Strong researchers work with '
        'strong researchers, so the search follows the most promising ones.</li>'
        '<li><b>A small AI meaning model</b>, running on this computer, checks that each person\'s subjects and '
        'papers really match the topic, not just the same words.</li>'
        '<li><b>Homepage check</b>: we read their homepage for a real sentence like “we are looking for PhD '
        'students” and copy it as proof. Website menus don\'t count.</li></ol>'
        '<table class="trail"><thead><tr><th>Profile opened</th><th>Why we opened it</th><th>On topic?</th>'
        f'<th>In the country?</th></tr></thead><tbody>{rows}</tbody></table></details>'
    )


def show(result, how):
    put(summary_html(result, how))
    here = result["here"]
    if here:
        taking = [p for p in here if taking_students(p)]
        with st.container(key="filters"):
            left_col, right_col = st.columns([3, 2])
            which = left_col.radio("Show", [f"All {len(here)}", f"Taking students {len(taking)}"],
                                   horizontal=True, label_visibility="collapsed")
            order = right_col.radio("Sort", ["Best match", "Most cited"], horizontal=True,
                                    label_visibility="collapsed")
        shown = taking if which.startswith("Taking") else here
        if order == "Most cited":
            shown = sorted(shown, key=lambda p: p["h_index"] or 0, reverse=True)
        put('<div class="index">' + "".join(entry_html(i, p) for i, p in enumerate(shown, start=1)) + "</div>")
    if result["country"] and result["elsewhere"]:
        put(also_html(result))
    put(method_html(result))


# ---------------- the page ----------------

put(f"<style>{(FOLDER / 'tokens.css').read_text(encoding='utf-8')}\n"
    f"{(FOLDER / 'app.css').read_text(encoding='utf-8')}</style>")

key = env_key() or st.session_state.get("user_key", "").strip()
left = searches_left_for(key) if key else None
meta = "Live from Google Scholar · via SerpApi"
if left == UNKNOWN_LEFT:
    meta += " · couldn't check searches left right now"
elif left is not None:
    meta += f" · {left} searches left on your key"
put(f'<header class="mast"><span class="mast__word">PhD Guide Finder</span>'
    f'<span class="mast__meta">{esc(meta)}</span></header>')

# What to show before the student searches: a shared link (?q=...&in=...) or the example.
if "result" not in st.session_state:
    asked_topic = st.query_params.get("q", "")
    asked_place = st.query_params.get("in", "") or None
    if asked_topic:
        st.session_state.result = load_saved(asked_topic, asked_place)
        st.session_state.how = "saved"
        st.session_state.prefill = (asked_topic, asked_place)
    else:
        st.session_state.result = load_saved(*EXAMPLE)
        st.session_state.how = "example"
        st.session_state.prefill = EXAMPLE

prefill_topic, prefill_place = st.session_state.prefill
with st.form("search", border=False):
    c1, c2, c3, c4, c5 = st.columns([2.35, 3.1, 0.35, 1.9, 1.4], vertical_alignment="bottom")
    c1.html('<p class="ask">Find guides working on</p>')
    topic = c2.text_input("Research topic", value=prefill_topic or "", placeholder="your research topic",
                          label_visibility="collapsed")
    c3.html('<p class="ask">in</p>')
    place = c4.selectbox("Country", COUNTRIES, label_visibility="collapsed",
                         index=COUNTRIES.index(prefill_place) if prefill_place in COUNTRIES else 0)
    go = c5.form_submit_button("Find guides")
    o1, o2 = st.columns([3, 2])
    depth = o1.radio("Search depth", DEPTHS, horizontal=True, label_visibility="collapsed")
    fresh = o2.checkbox("Search again, even if saved (uses searches)")

if not env_key():
    st.text_input("Your SerpApi key — needed only for new searches", type="password", key="user_key",
                  help="Kept only in this browser tab while it is open. Never saved or shared.")
    put('<p class="note">No key? <a href="https://serpapi.com/users/sign_up" target="_blank" rel="noopener">'
        'Get a free one at serpapi.com</a> — 250 searches a month.</p>')
    if key and left is None:
        put('<p class="note note--error">SerpApi did not accept that key. Copy it again from your SerpApi dashboard.</p>')

saved_links = [search_link(s["topic"], s["country"]) for s in saved_searches()][:6]
if saved_links:
    put('<p class="hint">Saved searches open free: ' + " · ".join(saved_links) + "</p>")

if go:
    st.session_state.pop("message", None)
    topic = topic.strip()
    place_value = None if place == ANYWHERE else place
    saved = load_saved(topic, place_value)
    result, how = None, ""
    if not topic:
        st.session_state.message = "Type a research topic first."
    elif saved and not fresh:
        result, how = saved, "saved"
    elif not key:
        st.session_state.message = "A new search needs a SerpApi key — paste yours in the box below the search."
    elif left is None:
        st.session_state.message = "SerpApi did not accept that key. Copy it again from your SerpApi dashboard."
    else:
        budget = finder.QUICK_BUDGET if depth == DEPTHS[0] else None
        with st.spinner("Reading Google Scholar through SerpApi and following co-authors… about a minute"):
            try:
                result, how = finder.run(topic, place_value, budget, key), "live"
            except Exception as problem:     # show the reason instead of a crash page, never the key
                st.session_state.message = f"The search stopped: {hide_key(str(problem), key)}"
        if result:
            result["depth"] = "quick" if budget else "thorough"
            DEMO.mkdir(exist_ok=True)       # keep it, so it opens free next time
            (DEMO / file_name(topic, place_value)).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            st.session_state.pop("left", None)   # the count changed: ask SerpApi again
    if result:
        st.session_state.result, st.session_state.how = result, how
        st.session_state.prefill = (topic, place_value)
        st.query_params.from_dict({"q": topic, "in": place_value or ""})
    st.rerun()

if st.session_state.get("message"):
    put(f'<p class="note note--error">{esc(st.session_state.message)}</p>')

if st.session_state.result:
    show(st.session_state.result, st.session_state.how)
elif st.session_state.prefill[0]:
    put('<p class="note">This topic hasn\'t been searched yet. Press <b>Find guides</b> to search it live.</p>')

put('<footer class="foot"><span>PhD Guide Finder · built with SerpApi for the SerpApi India Hackathon 2026</span>'
    f'<span><a href="{GITHUB}" target="_blank" rel="noopener">Open source on GitHub</a> · '
    'Results come from public pages — check each one before you email.</span></footer>')
