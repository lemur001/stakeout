"""Organization taxonomy and geography adapted from the supplied Backlink Hunter source."""

import re, math

TYPES = [
    # key, label, on by default, name pattern, NTEE prefixes, IRS subsections
    ("veterans", "Veterans posts", True, r"\blegion\b|\bvfw\b|veteran|amvets|vietnam vet|marine corps league|disabled american|fleet reserve|navy league|purple heart", ("W30",), ("19", "23")),
    ("fraternal", "Fraternal orders & lodges", True, r"knights of columbus|\belks\b|\bmoose\b|mason|\blodge\b|eastern star|odd fellows|eagles|fraternal order|sons of italy|shrine|ahepa|sons of norway|vasa order|order of", (), ("08", "10")),
    ("service", "Service clubs", True, r"\blions?\b|rotary|kiwanis|optimist|jaycee|exchange club|sertoma|civitan|zonta|soroptimist|woman'?s club|women'?s club|junior wom|\bgfwc\b|altrusa|pilot club|ruritan|newcomers", ("S80", "S81", "S82"), ()),
    ("library", "Friends of libraries", True, r"friends of .*librar|library friends|librar(y|ies) foundation", ("B70",), ()),
    ("schools", "PTAs, PTOs & boosters", True, r"\bptas?\b|\bptos?\b|parent.?teacher|booster|parents'? (club|associat|organi)|home and school|scholarship club|\bpto\b", ("B94", "B11", "B112", "B80"), ()),
    ("youth", "Youth sports & recreation", True, r"baseball|softball|soccer|football|hockey|basketball|lacrosse|\bswim|wrestling|volleyball|little league|pony league|athletic|\bcheer|youth sports|figure skating|bowling", ("N",), ()),
    ("animals", "Animal rescue", True, r"rescue|humane|animal|\bspca\b|\bpaws?\b|\bdogs?\b|\bcats?\b|feline|canine|greyhound", ("D20", "D", "D40"), ()),
    ("history", "Historical & heritage", True, r"historic|history|heritage|museum|genealog", ("A80", "A82", "A54", "A50"), ()),
    ("garden", "Garden, nature & environment", True, r"garden|horticult|\bnature\b|audubon|prairie|conservat|environment|\bbirds?\b|wildlife|green|tree|river|watershed|beautif", ("C", "D30", "D32", "D33", "D34"), ()),
    ("arts", "Arts, music & theater", True, r"\bband\b|orchestra|symphony|\bchoir\b|chorus|chorale|theat(er|re)|\bplayers\b|art guild|\barts?\b|music|\bdance\b|opera|singers|ballet|film", ("A",), ()),
    ("cultural", "Cultural & ethnic groups", True, r"polish|irish|greek|korean|filipino|indian|italian|mexican|ukrainian|japanese|kenjinkai|german|swedish|norwegian|assyrian|chinese|vietnamese|hispanic|latino|cultural|sister cit", ("A23",), ()),
    ("human", "Food pantries & human services", True, r"pantry|food bank|meals?\b|homeless|hunger|clothing|assistance|helping hands|caring|outreach|\bfish\b", ("K", "P", "L"), ()),
    ("civic", "Civic, neighborhood & community", True, r"civic|neighborhood|community|citizens|improvement association|\bdays\b|festival|parade|fourth of july", ("S", "W"), ("04",)),
    ("business", "Chambers & business groups", True, r"chamber|business association|merchants|business district|rotary foundation", ("S41", "S40"), ("06",)),
    ("hoa", "Homeowner & condo associations", True, r"homeowner|condominium|condo assoc|townhome|townhouse|property owners", ("S22",), ()),
    ("religious", "Churches & ministries", True, r"church|ministr|parish|congregation|temple|synagogue|mosque|fellowship|bible|gospel|diocese|evangel|baptist|lutheran|methodist|presbyterian|catholic", ("X",), ()),
    ("other", "Everything else", True, r"$^", (), ()),
]

TYPE_LABEL = {t[0]: t[1] for t in TYPES}

_TYPE_RE = [(t[0], re.compile(t[3], re.I), t[4], t[5]) for t in TYPES]

def classify(name, ntee, subsection):
    for key, rx, prefixes, subs in _TYPE_RE:
        if rx.search(name or ""):
            return key
    for key, rx, prefixes, subs in _TYPE_RE:
        if subsection in subs:
            return key
    for key, rx, prefixes, subs in _TYPE_RE:
        if ntee and any(ntee.startswith(p) for p in prefixes if len(p) > 1):
            return key
    for key, rx, prefixes, subs in _TYPE_RE:
        if ntee and any(ntee.startswith(p) for p in prefixes if len(p) == 1):
            return key
    return "other"

def nice(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    if not s:
        return s
    t = s.title()
    t = re.sub(r"\b(Pta|Pto|Vfw|Nfp|Inc|Usa|Gfwc|Amvets|Ii|Iii|Iv|Llc|Ymca|Ywca|Il)\b",
               lambda m: {"Inc": "Inc", "Nfp": "NFP", "Llc": "LLC"}.get(m.group(1), m.group(1).upper()), t)
    return re.sub(r"'S\b", "'s", t)

SHORT = [(r"international association of lions", "Lions Club"), (r"rotary international", "Rotary Club"),
         (r"kiwanis international", "Kiwanis Club"), (r"optimist international", "Optimist Club"),
         (r"american legion auxiliary", "American Legion Auxiliary"), (r"american legion", "American Legion"),
         (r"veterans of foreign wars", "VFW"), (r"knights of columbus", "Knights of Columbus"),
         (r"benevolent (and|&) protective order of elks", "Elks Lodge"), (r"loyal order of moose", "Moose Lodge"),
         (r"general federation of womens? clubs", "Woman's Club (GFWC)"), (r"illinois congress of parents|pta illinois|national congress of parents|parent teacher association", "PTA")]

def display_name(name, sort_name, city=""):
    """The BMF lists chapters under the national name ('International Association Of Lions Clubs') with the chapter
    in SORT_NAME ('Arlington Heights'). Show a short name plus the chapter so it's recognizable."""
    n, s = nice(name), nice(sort_name)
    short = next((lab for rx, lab in SHORT if re.search(rx, name or "", re.I)), "")
    if short:
        s = re.sub(r"\b0+(\d)", r"\1", s or nice(city))
        unit = {"American Legion": "Post", "American Legion Auxiliary": "Unit", "VFW": "Post", "Knights of Columbus": "Council",
                "Elks Lodge": "No.", "Moose Lodge": "No."}.get(short)
        if unit and re.match(r"\d", s):
            s = f"{unit} {s}"
        return f"{short} · {s}"
    if s and s.lower() not in n.lower() and len(s) > 2:
        return f"{n} · {s}"
    return n

def _tag(xml, *names):
    for n in names:
        m = re.search(rf"<(?:\w+:)?{n}>([^<]*)<", xml)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""

def clean_site(u):
    u = (u or "").strip()
    if not u or re.fullmatch(r"n/?a|none|no|na|n\.a\.|-|0|www|http:?|https:?|not applicable|no website", u, re.I):
        return ""
    if " " in u or "." not in u or "@" in u:
        return ""
    from ..core import public_url,DomainError
    try:return public_url(u if re.match(r'^https?://',u,re.I) else 'https://'+u,required=True)
    except DomainError:return ''

_RANGES = [("005", "005", "NY"), ("010", "027", "MA"), ("028", "029", "RI"), ("030", "038", "NH"), ("039", "049", "ME"),
           ("050", "054", "VT"), ("055", "055", "MA"), ("056", "059", "VT"), ("060", "069", "CT"), ("070", "089", "NJ"),
           ("100", "149", "NY"), ("150", "196", "PA"), ("197", "199", "DE"), ("200", "200", "DC"), ("201", "201", "VA"),
           ("202", "205", "DC"), ("206", "219", "MD"), ("220", "246", "VA"), ("247", "268", "WV"), ("270", "289", "NC"),
           ("290", "299", "SC"), ("300", "319", "GA"), ("320", "349", "FL"), ("350", "369", "AL"), ("370", "385", "TN"),
           ("386", "397", "MS"), ("398", "399", "GA"), ("400", "427", "KY"), ("430", "459", "OH"), ("460", "479", "IN"),
           ("480", "499", "MI"), ("500", "528", "IA"), ("530", "549", "WI"), ("550", "567", "MN"), ("569", "569", "DC"),
           ("570", "577", "SD"), ("580", "588", "ND"), ("590", "599", "MT"), ("600", "629", "IL"), ("630", "658", "MO"),
           ("660", "679", "KS"), ("680", "693", "NE"), ("700", "714", "LA"), ("716", "729", "AR"), ("730", "749", "OK"),
           ("750", "799", "TX"), ("800", "816", "CO"), ("820", "831", "WY"), ("832", "838", "ID"), ("840", "847", "UT"),
           ("850", "865", "AZ"), ("870", "884", "NM"), ("885", "885", "TX"), ("889", "898", "NV"), ("900", "961", "CA"),
           ("967", "968", "HI"), ("970", "979", "OR"), ("980", "994", "WA"), ("995", "999", "AK")]

def zip_state(z):
    p = (z or "")[:3]
    for a, b, st in _RANGES:
        if a <= p <= b:
            return st
    return ""

def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))
