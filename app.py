# The web page. Start it with:   streamlit run app.py
#
# Two modes:
#   Saved examples   - shows searches saved in the demo/ folder (free, no API key needed)
#   New live search  - runs a new search through SerpApi (key from .env, or typed into the page;
#                      Quick = about 7 searches, Thorough = about 11-13)
import hashlib
import json
import re
from pathlib import Path

import streamlit as st

import finder
from make_demo import file_name
from serp import env_key, searches_left

FOLDER = Path(__file__).parent
DEMO = FOLDER / "demo"
THIN_SUBJECT = 15   # fewer Scholar-page authors than this in the topic papers = warn the student
DEPTHS = ["Quick (about 7 searches)", "Thorough (about 11–13 searches)"]
COUNTRIES = ["Global (any country)", "India", "Singapore", "USA", "UK", "Germany", "Canada", "Australia",
             "Hong Kong", "China", "Japan", "Korea", "Netherlands", "Switzerland", "France", "Sweden"]

st.set_page_config(page_title="PhD Guide Finder", page_icon="🎓", layout="centered")


def searches_left_for(key):
    """Searches left on this key (free check). Remembered for this tab so the page stays fast."""
    tag = hashlib.sha256(key.encode()).hexdigest()
    remembered = st.session_state.get("left")
    if not remembered or remembered[0] != tag:
        st.session_state["left"] = (tag, searches_left(key))
    return st.session_state["left"][1]


def hide_key(message, key):
    """Error messages can contain the request address, which includes the key. Never show it."""
    message = re.sub(r"api_key=[^&\s]+", "api_key=•••", message)
    return message.replace(key, "•••") if key else message


def safe(text):
    """Stop Streamlit from reading $, *, _ or [ ] in scraped text as formatting."""
    for ch in "\\$*_[]`":
        text = (text or "").replace(ch, "\\" + ch)
    return text


def saved_searches():
    found = {}
    for path in sorted(DEMO.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found[f"{data['topic']}  —  {data['country'] or 'Global'}"] = data
    return found


def person_card(number, p):
    with st.container(border=True):
        st.markdown(f"#### {number}. {safe(p['name'])}")
        st.markdown(f"**{p['role']}** {safe(p['role_note'])}  \n{safe(p['job']) or 'Job not shown'}")
        st.caption(f"Country: {p['country']}  ·  h-index {p['h_index']} (how often their work is cited)"
                   f"  ·  email at {p['domain'] or 'not shown'}")

        if p["hiring"] == "Says so":
            student_places = {"PhD", "Master's", "Research assistant", "Not specified"}
            if student_places & set(p["offers"]):
                st.success("Taking students — " + ", ".join(p["offers"]))
            else:
                st.warning("Their homepage mentions openings, but for: " + ", ".join(p["offers"]) + " (not PhD)")
            st.markdown(f"> “{safe(p['proof'])}”")
            st.caption("Sentence copied from their homepage. Read it yourself before you email.")
        elif p["hiring"] == "Not mentioned":
            st.info("Their homepage doesn't mention open places. That doesn't mean no — email them to ask.")
        elif p["hiring"] == "Homepage would not open":
            st.info("We couldn't open their homepage to check. Email them to ask.")
        else:
            st.info("No homepage listed on their Google Scholar page. Email them to ask.")

        if p["subjects"]:
            st.markdown("**Research subjects:** " + "  ·  ".join(safe(s) for s in p["subjects"]))
        if p["papers"]:
            st.markdown("**Recent papers on your topic:**")
            for paper in p["papers"]:
                title = safe(paper["title"])
                st.markdown(f"- [{title}]({paper['link']}) ({paper['year']})" if paper["link"]
                            else f"- {title} ({paper['year']})")

        links = [f"[Google Scholar page]({p['scholar_link']})"]
        if p["homepage"]:
            links.append(f"[Homepage]({p['homepage']})")
        st.markdown("  ·  ".join(links))
        st.caption(f"How we found them: {safe(p['found_via'])} · on topic because of {p['topic_reason']}")


def show(result):
    where = f"in {result['country']}" if result["country"] else "worldwide"
    st.subheader(f"{len(result['here'])} researchers working on “{result['topic']}” {where}")
    stats = result["stats"]
    st.caption(f"Checked {stats['opened']} Google Scholar pages  ·  {stats['off_topic']} were not really "
               f"on this topic and were left out  ·  searched on {result['searched_on']}")

    # Tested on real data: science/engineering topics give ~45 authors with Scholar pages; English literature gave 9.
    if stats.get("scholar_authors", 99) < THIN_SUBJECT:
        st.warning("Few researchers in this subject have Google Scholar pages (common in literature, "
                   "languages and some law topics), so this list may be short. Also check university "
                   "department websites.")
    if not result["here"]:
        st.warning("Nobody found in this country for this topic. Try a broader topic, or Global.")
    for number, person in enumerate(result["here"], start=1):
        person_card(number, person)

    if result["elsewhere"]:
        with st.expander(f"Also strong on this topic, outside {result['country']} ({len(result['elsewhere'])})"):
            for number, person in enumerate(result["elsewhere"], start=1):
                person_card(number, person)

    with st.expander("How this search worked"):
        st.markdown(
            "1. **Google Scholar search (SerpApi):** recent, well-cited papers on your topic.\n"
            "2. **Google Scholar Author (SerpApi):** open the pages of the strongest authors.\n"
            "3. **Co-authors:** each page lists the people they publish with — strong researchers "
            "work with strong researchers. We follow the most promising ones.\n"
            "4. **Meaning model:** a small free AI model checks each person's subjects and papers "
            "really match your topic (not just the same words).\n"
            "5. **Homepage check:** we read their homepage for a sentence like *“we are looking for "
            "PhD students”*, and show it as proof.")
        st.dataframe(
            [{"Scholar page opened": t["name"], "Why we opened it": t["found_via"],
              "On your topic?": "yes" if t["on_topic"] else "no",
              "In your country?": "yes" if t["in_country"] else "no"} for t in result["trail"]],
            hide_index=True, width="stretch")


# ---------------- the page ----------------

st.title("🎓 PhD Guide Finder")
st.markdown("Find professors who are **actively researching your topic** — in India or anywhere — "
            "and see, **with proof from their own homepage**, whether they're taking students.")
st.caption("Built on live Google Scholar data through SerpApi. Free and open source.")

modes = ["Saved examples (free)", "New live search"]
mode = st.radio("Mode", modes, horizontal=True, label_visibility="collapsed")

if mode == modes[0]:
    searches = saved_searches()
    if not searches:
        st.info("No saved searches yet. Run a live search first.")
    else:
        names = list(searches)
        best = next((i for i, n in enumerate(names) if n.startswith("natural language processing") and "India" in n), 0)
        choice = st.selectbox("Choose a saved search", names, index=best)
        show(searches[choice])
else:
    key = env_key()
    if key:
        st.caption("Using the SerpApi key from your `.env` file.")
    else:
        key = st.text_input("Your SerpApi key", type="password",
                            help="Kept only in this browser tab while it is open. Never saved or shared.").strip()
        st.caption("No key? [Get a free one at serpapi.com](https://serpapi.com/users/sign_up) "
                   "— 250 searches a month.")
    left = searches_left_for(key) if key else None
    if key and left is None:
        st.error("SerpApi did not accept that key. Copy it again from your SerpApi dashboard.")
    elif key:
        st.caption(f"This key has **{left}** searches left this month.")

    with st.form("search"):
        topic = st.text_input("Your research topic", placeholder="natural language processing")
        country = st.selectbox("Where do you want to study?", COUNTRIES)
        depth = st.radio("Search depth", DEPTHS, horizontal=True)
        fresh = st.checkbox("Search again even if this topic was searched before (uses searches)")
        go = st.form_submit_button("Find guides", type="primary")

    if go:
        topic = topic.strip()
        place = None if country == COUNTRIES[0] else country
        saved = DEMO / file_name(topic, place)
        if not topic:
            st.error("Type a research topic first.")
        elif saved.exists() and not fresh:
            st.session_state["result"] = json.loads(saved.read_text(encoding="utf-8"))
            st.info("This topic was searched before, so the saved result is shown — free, no searches used. "
                    "Tick “Search again” for fresh results.")
        elif left is None:
            st.error("A new search needs a working SerpApi key (see above).")
        else:
            budget = finder.QUICK_BUDGET if depth == DEPTHS[0] else None
            with st.spinner("Reading Google Scholar through SerpApi and following co-authors… (about a minute)"):
                try:
                    result = finder.run(topic, place, budget, key)
                except Exception as problem:     # show the reason instead of a crash page, never the key
                    st.error(f"The search stopped: {hide_key(str(problem), key)}")
                    result = None
            if result:
                result["depth"] = "quick" if budget else "thorough"
                DEMO.mkdir(exist_ok=True)       # keep it, so it can be shown again for free
                saved.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                st.session_state["result"] = result
                st.session_state.pop("left", None)   # the count changed: ask SerpApi again next time
                st.rerun()
    if st.session_state.get("result"):
        show(st.session_state["result"])

st.divider()
st.caption("Results come from public Google Scholar pages and homepages. A missing “taking students” "
           "sentence doesn't mean no. Always read the professor's own page before you email.")
