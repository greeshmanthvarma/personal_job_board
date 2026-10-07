"""Title and location filter. A miss is a keyword reject. It is not the fit decision."""

import re
from dataclasses import dataclass

from applications.textutil import has_phrase, normalize

INCLUDE_PHRASES = (
    "software development engineer",
    "member of technical staff",
    "applied ai engineer",
    "generative ai engineer",
    "ai product engineer",
    "machine learning engineer",
    "developer tools engineer",
    "agent infrastructure engineer",
    "forward deployed engineer",
    "developer experience engineer",
    "full stack engineer",
    "full stack developer",
    "back end engineer",
    "back end developer",
    "front end engineer",
    "front end developer",
    "infrastructure engineer",
    "software engineer",
    "software developer",
    "product engineer",
    "genai engineer",
    "ai engineer",
    "agent engineer",
    "ml engineer",
    "ai ml engineer",
    "platform engineer",
    "search engineer",
    "retrieval engineer",
    "react engineer",
    "web engineer",
    "solutions engineer",
    "founding engineer",
    "sde",
    "swe",
)

OCCUPATION_EXCLUDES = (
    "account executive",
    "sales representative",
    "product manager",
    "program manager",
    "project manager",
    "business analyst",
    "it help desk",
    "help desk",
    "desktop support",
    "network administrator",
    "manual qa",
    "qa tester",
    "research scientist",
    "hardware engineer",
    "embedded engineer",
    "recruiter",
    "fpga",
    "rtl",
)

INTERN_EXCLUDES = (
    "internship",
    "intern",
    "co op",
    "coop",
    "apprenticeship",
    "student worker",
)

SENIORITY_EXCLUDES = (
    "senior",
    "sr",
    "principal",
    "distinguished",
    "fellow",
    "lead",
    "manager",
    "director",
    "vice president",
    "vp",
    "cto",
    "architect",
    "head of",
)

_STATE_ABBREV = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

_STATE_NAMES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "district of columbia",
)

_US_CITIES = (
    "san francisco bay area", "sf bay area", "san francisco", "bay area", "new york city",
    "los angeles", "san diego", "san jose", "palo alto", "mountain view", "menlo park",
    "redwood city", "santa clara", "sunnyvale", "salt lake city", "kansas city",
    "st louis", "saint louis", "jersey city", "el segundo", "ann arbor", "fort worth",
    "las vegas", "oklahoma city", "virginia beach", "colorado springs", "new orleans",
    "baton rouge", "des moines", "little rock", "sioux falls", "green bay",
    "san antonio", "el paso", "corpus christi", "college station", "chapel hill",
    "chattanooga", "huntsville", "montgomery", "tallahassee",
    "jacksonville", "fort lauderdale",
    "west palm beach", "miami", "tampa", "orlando", "atlanta", "savannah", "charlotte",
    "raleigh", "durham", "greensboro", "charleston", "richmond", "norfolk",
    "arlington", "alexandria", "bethesda", "tysons", "reston", "mclean", "ashburn",
    "baltimore", "philadelphia", "pittsburgh", "cleveland", "columbus", "cincinnati",
    "dayton", "toledo", "detroit", "grand rapids", "milwaukee", "madison",
    "minneapolis", "st paul", "saint paul", "chicago", "indianapolis", "nashville",
    "memphis", "knoxville", "louisville", "lexington", "houston", "dallas", "austin",
    "denver", "boulder", "phoenix", "tucson", "albuquerque", "boise", "seattle",
    "bellevue", "redmond", "kirkland", "tacoma", "spokane", "portland", "eugene",
    "sacramento", "oakland", "berkeley", "fremont", "irvine", "pasadena", "burbank",
    "glendale", "long beach", "santa monica", "culver city", "riverside", "boston",
    "somerville", "brooklyn", "manhattan", "queens", "bronx", "hoboken",
    "stamford", "providence", "hartford", "new haven", "buffalo", "rochester",
    "syracuse", "albany", "nyc", "sf",
)


_NON_US = (
    "indonesia", "thailand", "vietnam", "philippines", "hong kong", "austria",
    "malaysia", "taiwan", "shenzhen", "lausanne", "new zealand",
    "united kingdom", "great britain", "england", "scotland", "wales",
    "ireland", "uk", "europe", "emea", "germany", "berlin", "munich", "france",
    "netherlands", "amsterdam", "spain", "madrid", "sweden", "stockholm",
    "norway", "denmark", "finland", "switzerland", "zurich", "poland", "portugal",
    "italy", "india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi",
    "canada", "toronto", "montreal", "australia", "sydney", "melbourne",
    "singapore", "japan", "tokyo", "china", "beijing", "shanghai", "korea", "seoul",
    "israel", "tel aviv", "brazil", "mexico", "latam", "latin america", "africa",
    "nigeria", "kenya", "south africa", "uae", "dubai", "remote uk", "remote emea",
    "remote aus", "estonia", "romania", "belgium", "hungary", "czechia", "czech republic",
    "warsaw", "lisbon", "leuven", "budapest", "malmo", "bucharest", "gurugram",
)

@dataclass(frozen=True)
class TitleDecision:
    ok: bool
    reason: str


@dataclass(frozen=True)
class LocationDecision:
    action: str
    reason: str


def title_decision(title: str) -> TitleDecision:
    text = normalize(title)
    if not text:
        return TitleDecision(False, "title exclude: empty title")
    for phrase in OCCUPATION_EXCLUDES:
        if has_phrase(text, phrase):
            return TitleDecision(False, f"title exclude: {phrase} (title {title!r})")
    for phrase in INTERN_EXCLUDES:
        if has_phrase(text, phrase):
            return TitleDecision(False, f"title exclude: {phrase} (title {title!r})")
    member = has_phrase(text, "member of technical staff")
    hits = [phrase for phrase in SENIORITY_EXCLUDES if has_phrase(text, phrase)]
    if has_phrase(text, "staff") and not member:
        hits.append("staff")
    if member and not hits:
        return TitleDecision(True, "title include: member of technical staff")
    if hits:
        return TitleDecision(False, f"title exclude: {hits[0]} (title {title!r})")
    for phrase in INCLUDE_PHRASES:
        if has_phrase(text, phrase):
            return TitleDecision(True, f"title include: {phrase}")
    return TitleDecision(False, f"title exclude: outside include list (title {title!r})")


_US_EXCLUSION = re.compile(
    r"outside the (?:united states|u\.s\.|us)\b|"
    r"(?:u\.s\.|us|united states) residents (?:are )?not|"
    r"not (?:open to|available to|eligible for) (?:candidates in )?(?:the )?(?:us|u\.s\.|united states)|"
    r"excluding (?:the )?(?:us|u\.s\.|united states)|"
    r"no (?:us|u\.s\.) (?:remote|residents|candidates)",
    re.IGNORECASE,
)


def location_decision(location: str) -> LocationDecision:
    raw = (location or "").strip()
    if not raw:
        return LocationDecision("pass", "location not stated")
    if _US_EXCLUSION.search(raw):
        return LocationDecision("reject", f"location exclude: United States residents excluded ({raw!r})")
    country = re.search(r"\[country: ([^\]]+)\]", raw, re.IGNORECASE)
    if country:
        code = normalize(country.group(1))
        if code in {"us", "usa", "u s", "united states", "united states of america"}:
            return LocationDecision("pass", "location include: structured US address")
        return LocationDecision("reject", f"location exclude: structured country {country.group(1)!r}")
    if _strong_us(raw) or _state_signal(raw, normalize(raw)):
        return LocationDecision("pass", "location include: United States")
    text = normalize(raw)
    for phrase in _NON_US:
        if has_phrase(text, phrase):
            return LocationDecision("reject", f"location exclude: {phrase} ({raw!r})")
    if _allowed_us(raw):
        return LocationDecision("pass", "location include: known US city")
    leftover = re.sub(r"\b(?:office|headquarters|hq|hybrid|onsite|on site|remote|worldwide|global|anywhere)\b", " ", text)
    leftover = re.sub(r"\s+", " ", leftover).strip()
    if not leftover and re.search(r"\b(?:remote|worldwide|global|anywhere)\b", text):
        return LocationDecision(
            "uncertain",
            f"remote posting does not state that United States residents can work ({raw!r})",
        )
    return LocationDecision("uncertain", f"location does not state United States eligibility ({raw!r})")


def _allowed_us(raw: str) -> bool:
    if _strong_us(raw):
        return True
    text = normalize(raw)
    if _state_signal(raw, text):
        return True
    return any(has_phrase(text, city) for city in _US_CITIES)


def _strong_us(raw: str) -> bool:
    text = normalize(raw)
    if has_phrase(text, "united states") or has_phrase(text, "usa") or has_phrase(text, "u s") or has_phrase(text, "u s a"):
        return True
    return "US" in re.findall(r"\b[A-Z]{2}\b", raw)


def _state_signal(raw: str, text: str) -> bool:
    if any(token in _STATE_ABBREV for token in re.findall(r"\b[A-Z]{2}\b", raw)):
        return True
    return any(has_phrase(text, phrase) for phrase in _STATE_NAMES)
