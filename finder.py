# The engine: finds active researchers on a topic, using live SerpApi data.
#
#   1. Find recent papers on the topic                      (1 search)
#   2. Open the Scholar pages of the strongest authors      (1 search each)
#   3. Collect their co-authors                             (free: they come with step 2)
#   4. Keep opening the most promising co-authors           (1 search each)
#   5. Check each homepage for "taking students" sentences  (free: a normal web request)
#
# Try it:  python finder.py "medical image analysis"
#          python finder.py "medical image analysis" --country Singapore
import argparse
import hashlib
import math
import os
import re
from collections import defaultdict
from datetime import date

import requests

from serp import CACHE, search, spent

# Keep the meaning model quiet (no download bars or warnings in our output).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

LOOKUP_BUDGET = 10   # most Scholar pages we open for one student search (each new one = 1 search)
COUNTRY_BUDGET = 12  # a country search needs a few more pages to walk into that country's network
QUICK_BUDGET = 6     # "Quick" search on the web page: fewer pages, about 7 searches in total
SEEDS_WANTED = 3     # how many good starting researchers step 2 looks for
SEED_TRIES = 5       # ...and how many it may try before moving on
RECENT_YEARS = 3     # "recent" = papers from the last 3 years
PAPER_YEARS = 5      # step 1 looks at topic papers from the last 5 years
MIN_SEED_AUTHORS = 12  # fewer profile-linked authors than this on page 1 = read a second page of papers

PROFESSOR = "Professor or group leader"
STUDENT = "Student or postdoc"
RESEARCHER = "Researcher"
UNKNOWN = "Job not stated"
INDUSTRY = "Works at a company"   # cannot usually supervise a PhD, so left out of the results
SENIOR = "Senior researcher (job title not shown)"
SENIOR_H_INDEX = 20   # no title, but this much published work almost always means they lead a group

# Country -> the ending of university email addresses there (nus.edu.sg -> "sg").
COUNTRY_CODES = {
    "singapore": "sg", "india": "in", "uk": "uk", "germany": "de", "australia": "au", "canada": "ca",
    "china": "cn", "hong kong": "hk", "japan": "jp", "korea": "kr", "netherlands": "nl",
    "switzerland": "ch", "france": "fr", "italy": "it", "sweden": "se", "denmark": "dk",
    "finland": "fi", "austria": "at", "belgium": "be", "spain": "es", "ireland": "ie",
    "new zealand": "nz", "taiwan": "tw", "macau": "mo", "pakistan": "pk", "bangladesh": "bd",
    "sri lanka": "lk", "nepal": "np", "malaysia": "my", "vietnam": "vn", "thailand": "th",
    "saudi arabia": "sa", "uae": "ae", "iran": "ir", "turkey": "tr", "egypt": "eg", "brazil": "br",
    "israel": "il", "norway": "no", "poland": "pl", "portugal": "pt", "greece": "gr",
    "south africa": "za", "nigeria": "ng", "mexico": "mx", "philippines": "ph", "usa": "edu",
}
COUNTRY_ALIASES = {"united kingdom": "uk", "england": "uk", "united states": "usa", "us": "usa",
                   "america": "usa", "south korea": "korea"}

# Many universities use an email that does not end in the country code (thapar.edu, ieee.org, gmail).
# So we also look for these words in the person's job text.
COUNTRY_WORDS = {
    "india": ["india", "iit", "indian institute", "iisc", "iiser", "iiit", "nit",
              "national institute of technology", "thapar", "manipal", "amity", "vellore", "vit",
              "bits pilani", "anna university", "jamia", "aiims", "delhi", "mumbai", "bombay",
              "bengaluru", "bangalore", "chennai", "madras", "hyderabad", "kolkata", "kharagpur",
              "kanpur", "roorkee", "guwahati", "pune", "chandigarh", "patiala", "lucknow", "varanasi",
              "bhubaneswar", "noida", "gurugram", "jaipur", "indore", "kerala", "tamil nadu", "punjab",
              "madurai", "coimbatore", "trichy", "tiruchirappalli", "salem", "thiagarajar", "psg",
              "karnataka", "mysore", "mysuru", "mangalore", "kochi", "trivandrum", "thiruvananthapuram",
              "visakhapatnam", "vijayawada", "warangal", "nagpur", "bhopal", "ahmedabad", "surat",
              "vadodara", "patna", "ranchi", "dehradun", "srinagar", "jammu", "raipur", "goa",
              "andhra pradesh", "telangana", "maharashtra", "gujarat", "rajasthan", "odisha", "assam",
              "west bengal", "uttar pradesh", "haryana", "bihar", "srm", "sastra", "amrita"],
    "singapore": ["singapore", "nanyang", "a*star", "a-star", "duke-nus"],
    "uk": ["united kingdom", "uk", "england", "scotland", "oxford", "london", "edinburgh",
           "manchester", "imperial college"],
    "usa": ["usa", "united states"],
    "germany": ["germany", "max planck", "helmholtz", "fraunhofer", "munich", "berlin", "heidelberg"],
    "spain": ["catalonia", "barcelona", "madrid", "basque", "valencia", "upv/ehu"],
    "switzerland": ["eth zurich", "epfl", "zurich", "lausanne", "geneva"],
    "netherlands": ["amsterdam", "delft", "eindhoven", "utrecht", "leiden"],
    "france": ["paris", "inria", "cnrs", "sorbonne", "grenoble"],
    "italy": ["milan", "rome", "turin", "politecnico"],
    "hong kong": ["hong kong", "hkust", "cuhk"],
}

# Words that papers from a country usually contain (in the authors' addresses).
# Used to find STARTING researchers inside that country. Any other country uses its own name.
# Not the bare name for Singapore/Switzerland: the publisher "Springer Nature Singapore/Switzerland"
# prints those words on thousands of papers that were not written there.
COUNTRY_HINTS = {"india": "Indian Institute", "usa": "USA", "uk": "United Kingdom",
                 "singapore": "National University of Singapore", "switzerland": "ETH Zurich"}

HIRING_PHRASES = [
    "prospective student", "prospective phd", "phd position", "phd opening", "phd vacanc",
    "open position", "openings for", "we are recruiting", "i am recruiting", "actively recruiting",
    "looking for phd", "looking for motivated", "looking for self-motivated",
    "looking for highly motivated", "positions available", "positions are available",
    "fully funded", "join our lab", "join my lab", "join our group", "join my group",
    "accepting students", "accepting new students", "we are hiring",
]
# The proof must be a real sentence, not a website menu ("Prospective Students | Admissions | ...").
# So it must be short, mention who is wanted, and contain one of these "message" words.
HIRING_WHO = ["phd", "student", "postdoc", "position", "research assistant", "intern", "talent"]
HIRING_MESSAGE = ["looking for", "recruiting", "available", "welcome", "encourage", "seeking", "hiring",
                  "accepting", "apply", "email", "contact me", "interested", "join", "openings for"]
PROOF_MAX_LENGTH = 300


# ---------- small helpers ----------

def email_domain(text):
    return (text or "").replace("Verified email at", "").strip().lower()


COMPANIES = ["google", "deepmind", "meta", "facebook", "microsoft", "openai", "anthropic", "amazon", "apple",
             "nvidia", "ibm", "adobe", "tencent", "alibaba", "baidu", "bytedance", "huawei", "samsung", "intel",
             "salesforce", "tata consultancy", "infosys", "wipro", "accenture", "bosch", "siemens", "qualcomm"]
ACADEMIC_WORDS = ["university", "institute", "college", "school", "academy", "hospital", "laboratory", "centre",
                  "center", "a*star"]
MAIL_PROVIDERS = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "qq.com", "163.com", "126.com",
                  "icloud.com", "live.com", "protonmail.com", "foxmail.com"]


def role_of(job, domain=""):
    job = (job or "").lower()
    if any(w in job for w in ["phd student", "ph.d. student", "phd candidate", "student", "postdoc", "post-doc", "intern"]):
        return STUDENT
    if any(w in job for w in ["professor", "prof.", "lecturer", "faculty", "chair", "principal investigator",
                              "group leader", "head of", "director"]):
        return PROFESSOR
    company_email = domain.endswith((".com", ".ai", ".io")) and domain not in MAIL_PROVIDERS
    if any(has_word(job, c) for c in COMPANIES) or (company_email and not any(w in job for w in ACADEMIC_WORDS)):
        return INDUSTRY
    if any(has_word(job, w) for w in ["scientist", "researcher", "research fellow", "engineer"]):
        return RESEARCHER
    return UNKNOWN


def standard_country(name):
    name = (name or "").strip().lower()
    return COUNTRY_ALIASES.get(name, name) or None


def has_word(text, word):
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def country_of(person):
    """Best guess of where a person works, from their email ending and their job text."""
    job = person["job"].lower()
    for not_a_country in ["beth israel", "new mexico", "new england"]:   # US places that contain a country word
        job = job.replace(not_a_country, " ")
    ending = person["domain"].rsplit(".", 1)[-1] if person["domain"] else ""
    if ending == "eus":                          # Basque Country email ending
        return "spain"
    for country, code in COUNTRY_CODES.items():
        if code == ending and code != "edu":
            return country
    for country in COUNTRY_CODES:                # a country named in the job text wins ("Punjab, Pakistan")
        if has_word(job, country):
            return country
    for country, words in COUNTRY_WORDS.items():
        if any(has_word(job, w) for w in words):
            return country
    return "usa" if ending == "edu" else None   # ".edu" with no other clue is almost always the USA


def in_country(person, country):
    return not country or country_of(person) == standard_country(country)


# ---------- talking to SerpApi ----------

def linked_authors(papers):
    """How many different authors in these papers have a Google Scholar profile we can open."""
    return len({a["author_id"] for p in papers for a in (p.get("publication_info") or {}).get("authors", [])
                if a.get("author_id")})


def find_paper_authors(topic, country=None, key=None):
    """Step 1: recent papers on the topic. Returns author IDs, strongest first (weighted by citations).
    With a country, the search also asks for that country's name, so the papers come from there.
    Papers from the last 5 years: old enough to have citations (which show strong groups),
    and we separately check that every person is STILL publishing on the topic."""
    since = date.today().year - PAPER_YEARS
    query = f'"{topic}"'
    if country:
        country = standard_country(country)
        query += f' "{COUNTRY_HINTS.get(country, country.title())}"'
    params = {"engine": "google_scholar", "q": query, "as_ylo": since, "num": 20}
    papers = search(params, key).get("organic_results", [])
    if linked_authors(papers) < MIN_SEED_AUTHORS:
        # For some topics Scholar links few author profiles on the first page (seen with
        # "speech recognition": 5 linked authors vs ~45 usually). Read one more page of papers.
        papers += search({**params, "start": 20}, key).get("organic_results", [])
    score = defaultdict(float)
    for paper in papers:
        cites = ((paper.get("inline_links") or {}).get("cited_by") or {}).get("total") or 0
        for author in (paper.get("publication_info") or {}).get("authors", []):
            if author.get("author_id"):
                score[author["author_id"]] += 1 + math.log1p(cites)
    return sorted(score, key=score.get, reverse=True)


def open_profile(author_id, key=None):
    """Steps 2 and 4: one person's Google Scholar page."""
    data = search({"engine": "google_scholar_author", "author_id": author_id, "sort": "pubdate"}, key)
    if "error" in data:
        return None
    author = data.get("author", {})
    numbers = {}
    for row in data.get("cited_by", {}).get("table", []):
        numbers.update(row)
    return {
        "id": author_id,
        "name": author.get("name", "?"),
        "job": author.get("affiliations") or "",
        "domain": email_domain(author.get("email")),
        "interests": [i.get("title", "") for i in author.get("interests", [])],
        "homepage": author.get("website"),
        "h_index": numbers.get("h_index", {}).get("all"),
        "articles": data.get("articles", []),
        "co_authors": [
            {"id": c.get("author_id"), "name": c.get("name", "?"),
             "job": c.get("affiliations") or "", "domain": email_domain(c.get("email"))}
            for c in data.get("co_authors", [])
        ],
        "scholar_link": f"https://scholar.google.com/citations?user={author_id}",
    }


# ---------- judging a person ----------

_model = None


def meaning_model():
    """The small free 'meaning' model (all-MiniLM-L6-v2). It turns text into numbers so that
    texts with a similar MEANING get similar numbers. Loaded once, the first time it is needed."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        try:     # use the copy already on this computer, if there is one
            _model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        except Exception:   # first run: download it (about 90 MB, once)
            _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def closeness(topic, texts):
    """How close in meaning each text is to the topic: about 0 (unrelated) to 1 (same meaning)."""
    from sentence_transformers import util
    model = meaning_model()
    return util.cos_sim(model.encode(topic), model.encode(texts))[0].tolist()


# Thresholds chosen by testing on ~75 real researchers across two topics.
# Each listed subject is compared on its own ("NLP, Speech" would blur the meaning if joined).
SUBJECT_CLEARLY = 0.65    # one listed subject matches strongly: enough on its own
SUBJECT_PARTLY = 0.40     # ...or a subject matches moderately AND
PAPERS_MATCH = 0.36       # ...their 3 closest recent papers match
NO_SUBJECTS_PAPERS = 0.50 # people who list no subjects: their papers must match well
PAPER_SHOWN = 0.40        # a recent paper counts as "on the topic" (shown to the student)

SHORT_FORMS = {
    "nlp": "natural language processing", "cv": "computer vision", "ml": "machine learning",
    "ai": "artificial intelligence", "llm": "large language models", "llms": "large language models",
    "rl": "reinforcement learning", "mri": "magnetic resonance imaging", "iot": "internet of things",
    "hci": "human computer interaction", "dl": "deep learning", "gnn": "graph neural networks",
    "gnns": "graph neural networks", "ir": "information retrieval", "asr": "speech recognition",
    "pv": "photovoltaics", "ev": "electric vehicles", "evs": "electric vehicles",
}


# Conference books and editor credits are listed on Scholar pages but are not the person's own research.
NOT_A_PAPER = re.compile(r"^\s*(proceedings|findings of|workshop on|book of abstracts|correction)", re.I)


def expand(text):
    """'LLMs, NLP' -> 'large language models, natural language processing' (the model knows full words better)."""
    return re.sub(r"[A-Za-z]+", lambda m: SHORT_FORMS.get(m.group(0).lower(), m.group(0)), text)


def check_topic(profile, topic):
    """Is this person really working on the topic? Returns (yes/no, reason, their topic papers)."""
    topic = expand(topic)
    since = date.today().year - RECENT_YEARS
    recent = [a for a in profile["articles"]
              if str(a.get("year", "")).isdigit() and int(a["year"]) >= since
              and not NOT_A_PAPER.match(a.get("title", ""))][:15]
    subjects = [expand(s) for s in profile["interests"] if s.strip()]

    subject_score = max(closeness(topic, subjects)) if subjects else 0.0
    paper_scores = closeness(topic, [a.get("title", "") for a in recent]) if recent else []
    top3 = sorted(paper_scores, reverse=True)[:3]
    papers_score = sum(top3) / len(top3) if top3 else 0.0
    topic_papers, seen = [], set()
    for paper, score in sorted(zip(recent, paper_scores), key=lambda x: -x[1]):
        title = paper.get("title", "").strip().lower()
        if score >= PAPER_SHOWN and title not in seen:    # Scholar sometimes lists the same paper twice
            topic_papers.append(paper)
            seen.add(title)

    profile["topic_score"] = round(max(subject_score, papers_score), 2)
    if subject_score >= SUBJECT_CLEARLY:
        return True, "their listed subjects", topic_papers
    if subject_score >= SUBJECT_PARTLY and papers_score >= PAPERS_MATCH:
        return True, "their subjects and recent papers", topic_papers
    if not subjects and papers_score >= NO_SUBJECTS_PAPERS:
        return True, "their recent papers", topic_papers
    return False, "", topic_papers


def page_text(url):
    """Download a web page once, keep a copy (free, not SerpApi), and return its plain text."""
    saved = CACHE / "pages" / (hashlib.md5(url.encode()).hexdigest() + ".html")
    if saved.exists():
        html = saved.read_text(encoding="utf-8")
    else:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()          # "Forbidden", "Not found" etc. count as "would not open"
        html = response.text
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(html, encoding="utf-8")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


ABBREVIATIONS = ("ph.d", "dr", "prof", "e.g", "i.e", "etc", "vs", "no")   # a full stop here is not a sentence end


def sentence_end(text, position):
    """Where the sentence that continues at `position` ends (-1 if it never does)."""
    while True:
        stops = [i for i in (text.find(". ", position), text.find("! ", position), text.find("? ", position)) if i >= 0]
        if not stops:
            return -1
        stop = min(stops)
        if text[stop] == "." and text[max(0, stop - 5):stop].lower().endswith(ABBREVIATIONS):
            position = stop + 1
            continue
        return stop


def sentence_around(text, start, end):
    """The whole sentence that contains text[start:end], so the proof is not cut mid-word."""
    left = max(text.rfind(". ", 0, start), text.rfind("! ", 0, start), text.rfind("? ", 0, start))
    left = left + 2 if left >= 0 and start - left < 250 else max(0, start - 120)
    stop = sentence_end(text, end)
    right = stop + 1 if stop >= 0 and stop - end < 250 else end + 150
    return text[left:right].strip()


def check_hiring(text):
    """Step 5: does the homepage say they are taking students? Returns (answer, proof sentence)."""
    lower = text.lower()
    for phrase in HIRING_PHRASES:
        start = 0
        while (at := lower.find(phrase, start)) >= 0:      # every place the phrase appears
            start = at + 1
            sentence = sentence_around(text, at, at + len(phrase))
            plain = sentence.lower()
            if (len(sentence) <= PROOF_MAX_LENGTH
                    and any(w in plain for w in HIRING_WHO)
                    and any(w in plain for w in HIRING_MESSAGE)):
                # start the proof at "We ..." or "I ..." when the page ran two sentences together
                here = plain.find(phrase)
                cut = max(sentence.rfind(" We ", 0, here + 4), sentence.rfind(" I ", 0, here + 3))
                if cut > 0:
                    return "Says so", sentence[cut + 1:]
                if here > 100:     # long run-on text (menus, captions) before the phrase: start at the phrase
                    return "Says so", sentence[here:]
                return "Says so", sentence
    return "Not mentioned", ""


def title_on_page(text):
    """When Scholar shows no job title, the homepage often does (e.g. 'Assistant Professor')."""
    lower = text.lower()
    for title in ["assistant professor", "associate professor", "full professor", "chair professor", "lecturer"]:
        if title in lower:
            return title
    return None


def describe(person):
    """Fill in role and 'taking students?' for a person we will show."""
    person["role"] = role_of(person["job"], person["domain"])
    person["role_note"] = ""
    if not person["homepage"]:
        person["hiring"], person["proof"] = "No homepage listed", ""
        return
    try:
        text = page_text(person["homepage"])
    except requests.RequestException:
        person["hiring"], person["proof"] = "Homepage would not open", ""
        return
    person["hiring"], person["proof"] = check_hiring(text)
    if person["role"] == UNKNOWN and title_on_page(text):
        person["role"], person["role_note"] = PROFESSOR, f'("{title_on_page(text)}" on their homepage)'


def settle_role(person):
    if person["role"] == UNKNOWN and (person["h_index"] or 0) >= SENIOR_H_INDEX:
        person["role"] = SENIOR


def rank(person):
    score = 3 if person["role"] in (PROFESSOR, SENIOR) else 0
    score += 2 if person["hiring"] == "Says so" else 0
    score += min(len(person["topic_papers"]), 5) * 0.4      # active on the topic right now (up to 2)
    score += min(person["h_index"] or 0, 60) / 20           # experience: h-index 60 or more = full 3 points
    return score


# ---------- the whole search ----------

def find_researchers(topic, country=None, budget=None, key=None):
    """Returns (people in the chosen country, strong people elsewhere, stats).
    With no country, everyone is in the first list (global search)."""
    budget = budget or (COUNTRY_BUDGET if country else LOOKUP_BUDGET)
    spent_before = spent["searches"]      # count only THIS search (the web page runs many)
    opened = {}                      # author_id -> profile
    pool = {}                        # author_id -> {"person": ..., "works_with": set of names}

    def open_and_expand(author_id, found_via):
        profile = open_profile(author_id, key)
        if profile is None:
            return None
        profile["on_topic"], profile["topic_reason"], profile["topic_papers"] = check_topic(profile, topic)
        profile["found_via"] = found_via
        opened[author_id] = profile
        pool.pop(author_id, None)
        if profile["on_topic"]:      # only trust the co-authors of people who really work on the topic
            for co in profile["co_authors"]:
                if co["id"] and co["id"] not in opened:
                    entry = pool.setdefault(co["id"], {"person": co, "works_with": set()})
                    entry["works_with"].add(profile["name"])
        return profile

    # Step 2: starting researchers from the topic papers (from the chosen country, if there is one)
    paper_authors = find_paper_authors(topic, country, key)
    scholar_authors = len(paper_authors)     # few here = this subject rarely uses Google Scholar
    good, tries = 0, 0
    while paper_authors and good < SEEDS_WANTED and tries < SEED_TRIES and len(opened) < budget:
        tries += 1
        profile = open_and_expand(paper_authors.pop(0), "wrote recent papers on the topic")
        if profile and profile["on_topic"]:
            good += 1

    # Steps 3-4: keep opening the most promising co-author
    def promise(entry):
        person = entry["person"]
        score = len(entry["works_with"])                # works with several people we trust
        if role_of(person["job"], person["domain"]) == PROFESSOR:
            score += 2
        if country and in_country(person, country):
            score += 5
        return score

    while len(opened) < budget and (pool or paper_authors):
        if pool:
            best = max(pool, key=lambda aid: (promise(pool[aid]), aid))
            works_with = ", ".join(sorted(pool[best]["works_with"]))
            open_and_expand(best, f"works with {works_with}")
        else:   # no co-authors left to follow: go back to the next author of the topic papers
            next_author = paper_authors.pop(0)
            if next_author not in opened:
                open_and_expand(next_author, "wrote recent papers on the topic")

    # Step 5 + ranking
    on_topic = [p for p in opened.values() if p["on_topic"]]
    academics = [p for p in on_topic if role_of(p["job"], p["domain"]) != INDUSTRY]
    here = [p for p in academics if in_country(p, country)]
    elsewhere = [p for p in academics if not in_country(p, country)]
    for person in here + elsewhere:
        describe(person)
        settle_role(person)
    here.sort(key=rank, reverse=True)
    elsewhere.sort(key=rank, reverse=True)

    stats = {
        "opened": len(opened),
        "off_topic": len(opened) - len(on_topic),
        "industry": len(on_topic) - len(academics),
        "scholar_authors": scholar_authors,
        "new_searches": spent["searches"] - spent_before,
        # every page we opened, in order: shows HOW the search travelled through the network
        "trail": [(p["name"], p["found_via"], p["on_topic"], in_country(p, country), p["domain"])
                  for p in opened.values()],
    }
    return here, elsewhere, stats


COUNTRY_DISPLAY = {"usa": "USA", "uk": "UK", "uae": "UAE"}

# What the proof sentence says they are offering, so a PhD seeker can tell "PhD" from "internship".
OFFER_WORDS = {
    "PhD": ["phd", "ph.d", "doctoral"],
    "Master's": ["master", "ms (by research)", "m.s.", "mtech", "m.tech"],
    "Postdoc": ["postdoc", "post-doc", "postdoctoral"],
    "Research assistant": ["research assistant", "/ra/", " ra,", " ra ", "ras,", "ras "],
    "Internship": ["intern"],
    "Visiting student": ["visiting"],
}


def offers(proof):
    plain = f" {proof.lower()} "
    found = [kind for kind, words in OFFER_WORDS.items() if any(w in plain for w in words)]
    return found or (["Not specified"] if proof else [])


def country_name(person):
    country = country_of(person)
    return COUNTRY_DISPLAY.get(country, country.title()) if country else "Not sure"


def card(person):
    """Only what the web page shows: small enough to save as demo data."""
    return {
        "name": person["name"], "role": person["role"], "role_note": person["role_note"],
        "job": person["job"], "domain": person["domain"], "country": country_name(person),
        "subjects": person["interests"], "topic_reason": person["topic_reason"],
        "found_via": person["found_via"], "h_index": person["h_index"],
        "papers": [{"title": a.get("title", ""), "year": a.get("year", ""), "link": a.get("link", "")}
                   for a in person["topic_papers"][:3]],
        "hiring": person["hiring"], "proof": person["proof"], "offers": offers(person["proof"]),
        "homepage": person["homepage"],
        "scholar_link": person["scholar_link"],
    }


def run(topic, country=None, budget=None, key=None):
    """One complete student search, returned as plain data (used by the web page and the demo files)."""
    here, elsewhere, stats = find_researchers(topic, country, budget, key)
    return {
        "topic": topic, "country": country, "searched_on": date.today().isoformat(),
        "here": [card(p) for p in here], "elsewhere": [card(p) for p in elsewhere],
        "stats": {k: v for k, v in stats.items() if k != "trail"},
        "trail": [{"name": n, "found_via": via, "on_topic": ok, "in_country": inside, "domain": d}
                  for n, via, ok, inside, d in stats["trail"]],
    }


def print_person(number, p):
    print(f"{number}. {p['name']}  -  {p['role']} {p['role_note']}  (h-index {p['h_index']})")
    print(f"   Where:      {p['job']}  [{p['domain'] or 'email not shown'}]  country: {country_of(p) or '?'}")
    print(f"   Subjects:   {', '.join(p['interests']) or '-'}")
    print(f"   On topic:   yes, from {p['topic_reason']}")
    print(f"   Found by:   {p['found_via']}")
    for paper in p["topic_papers"][:2]:
        print(f"   Paper:      {paper.get('year')}  {paper.get('title')}")
    print(f"   Students:   {p['hiring']}" + (f'  ->  "{p["proof"]}"' if p["proof"] else ""))
    print(f"   Scholar:    {p['scholar_link']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Find active researchers on a topic.")
    parser.add_argument("topic")
    parser.add_argument("--country", default=None)
    parser.add_argument("--budget", type=int, default=None, help="most Scholar pages to open")
    args = parser.parse_args()

    here, elsewhere, stats = find_researchers(args.topic, args.country, args.budget)
    where = f" in {args.country}" if args.country else " (global)"
    print(f'\nResearchers working on "{args.topic}"{where}: {len(here)}\n')
    for number, p in enumerate(here, start=1):
        print_person(number, p)
    if args.country and elsewhere:
        print(f"Also strong on this topic, outside {args.country}: "
              + "; ".join(f"{p['name']} ({p['domain'] or '?'})" for p in elsewhere))
    print(f"\nScholar pages opened: {stats['opened']}  |  not on topic: {stats['off_topic']}"
          f"  |  new searches used: {stats['new_searches']}")


if __name__ == "__main__":
    main()
