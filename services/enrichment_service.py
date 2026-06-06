"""Enrichment pipeline: PeeringDB, subsea cables, hardware parsing, RDAP."""

import re
import math
import httpx

# ── PeeringDB / IXP Fabric Local Mapping ──────────────────────────

IXP_FABRICS = {
    "singapore": [
        {"name": "Equinix SG1", "type": "IXP", "asn": "AS133165", "peers": 180},
        {"name": "SGIX", "type": "IXP", "asn": "AS45753", "peers": 85},
        {"name": "AMS-IX Singapore", "type": "IXP", "asn": "AS1200", "peers": 45},
        {"name": "BBIX Singapore", "type": "IXP", "asn": "AS38028", "peers": 30},
    ],
    "jakarta": [
        {"name": "OpenIXP", "type": "IXP", "asn": "AS0", "peers": 60},
        {"name": "IIX", "type": "IXP", "asn": "AS135448", "peers": 40},
        {"name": "Equinix JK1", "type": "IXP", "asn": "AS15830", "peers": 35},
        {"name": "CDIX", "type": "IXP", "asn": "AS63956", "peers": 20},
    ],
    "tokyo": [
        {"name": "Equinix TY2", "type": "IXP", "asn": "AS15830", "peers": 200},
        {"name": "JPNAP", "type": "IXP", "asn": "AS7527", "peers": 160},
        {"name": "BBIX Tokyo", "type": "IXP", "asn": "AS38028", "peers": 90},
    ],
    "london": [
        {"name": "LINX LON1", "type": "IXP", "asn": "AS8714", "peers": 900},
        {"name": "LONAP", "type": "IXP", "asn": "AS8330", "peers": 200},
        {"name": "Equinix LD4/LD5", "type": "IXP", "asn": "AS15830", "peers": 400},
    ],
    "frankfurt": [
        {"name": "DE-CIX Frankfurt", "type": "IXP", "asn": "AS6695", "peers": 1050},
        {"name": "Equinix FR2/FR5", "type": "IXP", "asn": "AS15830", "peers": 350},
    ],
    "amsterdam": [
        {"name": "AMS-IX", "type": "IXP", "asn": "AS1200", "peers": 880},
        {"name": "NL-ix", "type": "IXP", "asn": "AS34307", "peers": 300},
    ],
    "hongkong": [
        {"name": "HKIX", "type": "IXP", "asn": "AS4635", "peers": 250},
        {"name": "Equinix HK1", "type": "IXP", "asn": "AS15830", "peers": 150},
    ],
    "sydney": [
        {"name": "Equinix SY3", "type": "IXP", "asn": "AS15830", "peers": 120},
        {"name": "IX Australia (Sydney)", "type": "IXP", "asn": "AS7604", "peers": 80},
    ],
    "sanjose": [{"name": "Equinix SV1/SV5", "type": "IXP", "asn": "AS15830", "peers": 220}],
    "newyork": [{"name": "DE-CIX New York", "type": "IXP", "asn": "AS51107", "peers": 180}],
    "losangeles": [{"name": "Equinix LA1", "type": "IXP", "asn": "AS15830", "peers": 160}],
    "ashburn": [{"name": "Equinix DC2/DC6", "type": "IXP", "asn": "AS15830", "peers": 350}],
    "dubai": [{"name": "UAE-IX", "type": "IXP", "asn": "AS211309", "peers": 50}],
    "mumbai": [{"name": "DE-CIX Mumbai", "type": "IXP", "asn": "AS51107", "peers": 120}],
    "seoul": [{"name": "KINX", "type": "IXP", "asn": "AS9286", "peers": 90}],
}

COMMON_PNIS = {
    "google": "Google Private Network Interconnect (PNI)",
    "facebook": "Meta Private WAN Interconnect (PNI)",
    "meta": "Meta Private WAN Interconnect (PNI)",
    "cloudflare": "Cloudflare Private Interconnect (PNI)",
    "akamai": "Akamai Private Interconnect (PNI)",
    "fastly": "Fastly Private Interconnect (PNI)",
    "microsoft": "Microsoft Azure Private Interconnect (PNI)",
    "amazon": "AWS Direct Connect (PNI)",
    "apple": "Apple Private WAN (PNI)",
}

def lookup_peering_fabric(city_hint, org_hint):
    """Return IXP/PNI info for a given city and org hint."""
    if not city_hint:
        city_hint = ""
    city_lower = city_hint.lower().replace(" ", "")
    for cname, fabrics in IXP_FABRICS.items():
        if cname in city_lower or city_lower in cname:
            return {"fabric": fabrics[0]["name"], "type": "IXP",
                    "full_list": [f["name"] for f in fabrics[:3]]}
    for org_key, pni_name in COMMON_PNIS.items():
        if org_hint and org_key in org_hint.lower():
            return {"fabric": pni_name, "type": "PNI", "full_list": [pni_name]}
    return None

def detect_interconnect(prev_org, cur_org, prev_city, cur_city):
    """Detects boundary handoff between different ISPs."""
    if not prev_org or not cur_org:
        return {"interconnect": "Unspecified Core Fabric"}
    p_clean = prev_org.lower().strip()
    c_clean = cur_org.lower().strip()
    if p_clean == c_clean:
        return {"interconnect": "Internal Backbone (same AS)"}
    # Different ISP → boundary handoff
    city = cur_city or prev_city or ""
    peering = lookup_peering_fabric(city, cur_org)
    if peering:
        return {"interconnect": peering["fabric"],
                "interconnect_type": peering["type"],
                "ixp_options": peering.get("full_list", [])}
    return {"interconnect": "BGP Transit (PNI or upstream)"}

# ── Subsea Cable Matcher ──────────────────────────────────────────

SUBMARINE_CABLES = {
    ("singapore", "jakarta"): "SEA-ME-WE 5 Submarine Cable System",
    ("jakarta", "singapore"): "SEA-ME-WE 5 Submarine Cable System",
    ("singapore", "mumbai"): "SEA-ME-WE 5 Submarine Cable System",
    ("mumbai", "singapore"): "SEA-ME-WE 5 Submarine Cable System",
    ("singapore", "chennai"): "i2i / TATA TGN-Intra Asia Cable",
    ("singapore", "tokyo"): "AAG (Asia-America Gateway) Cable Network",
    ("tokyo", "singapore"): "AAG (Asia-America Gateway) Cable Network",
    ("singapore", "sydney"): "SEA-ME-WE 3 / Australia-Singapore Cable",
    ("sydney", "singapore"): "SEA-ME-WE 3 / Australia-Singapore Cable",
    ("singapore", "hongkong"): "AAG (Asia-America Gateway) / SJC Cable",
    ("hongkong", "singapore"): "AAG (Asia-America Gateway) / SJC Cable",
    ("singapore", "losangeles"): "AAG + TPC (Trans-Pacific) Cable System",
    ("losangeles", "singapore"): "AAG + TPC (Trans-Pacific) Cable System",
    ("tokyo", "losangeles"): "FASTER / Unity Transpacific Cable System",
    ("losangeles", "tokyo"): "FASTER / Unity Transpacific Cable System",
    ("tokyo", "seattle"): "FASTER / New Cross Pacific Cable",
    ("sanjose", "tokyo"): "FASTER / Unity Transpacific Cable System",
    ("london", "newyork"): "TAT-14 / AC-1 Transatlantic Cable",
    ("newyork", "london"): "TAT-14 / AC-1 Transatlantic Cable",
    ("london", "ashburn"): "TAT-14 / GTT Atlantic Cable",
    ("mumbai", "london"): "SEA-ME-WE 5 / I-ME-WE Cable System",
    ("london", "mumbai"): "SEA-ME-WE 5 / I-ME-WE Cable System",
    ("dubai", "mumbai"): "FALCON / FLAG Cable System",
    ("mumbai", "dubai"): "FALCON / FLAG Cable System",
    ("frankfurt", "london"): "TAT-14/GTT Cross-Channel",
    ("amsterdam", "london"): "UK-Netherlands 14 / CrossChannel",
    ("london", "frankfurt"): "TAT-14/GTT Cross-Channel",
    ("sydney", "losangeles"): "Southern Cross Cable Network",
    ("losangeles", "sydney"): "Southern Cross Cable Network",
    ("losangeles", "sanjose"): "Terrestrial Backbone (US West Coast)",
    ("hongkong", "tokyo"): "APCN-2 / ASE Cable System",
    ("tokyo", "hongkong"): "APCN-2 / ASE Cable System",
    ("jakarta", "perth"): "SEA-ME-WE 5 Submarine Cable System",
    ("perth", "jakarta"): "SEA-ME-WE 5 Submarine Cable System",
    ("singapore", "perth"): "SEA-ME-WE 3 / ASC Cable Network",
    ("perth", "singapore"): "SEA-ME-WE 3 / ASC Cable Network",
    ("miami", "saopaulo"): "AMX-1 / Seabras-1 Transatlantic Cable",
    ("saopaulo", "miami"): "AMX-1 / Seabras-1 Transatlantic Cable",
    ("london", "durban"): "SAFE / WACS Submarine Cable",
    ("durban", "london"): "SAFE / WACS Submarine Cable",
    ("singapore", "dubai"): "SEA-ME-WE 5 Submarine Cable System",
    ("dubai", "singapore"): "SEA-ME-WE 5 Submarine Cable System",
    ("london", "paris"): "Terrestrial / Cross-Channel Fiber",
    ("paris", "london"): "Terrestrial / Cross-Channel Fiber",
}

OCEAN_BASINS = {
    "South China Sea": 0, "Java Sea": 0, "Indian Ocean": 0,
    "Pacific Ocean": 1, "Atlantic Ocean": 2, "Caribbean Sea": 2,
    "Mediterranean Sea": 3, "North Sea": 4, "English Channel": 5,
}

def detect_submarine_cable(prev_city, cur_city, prev_lat, prev_lng, cur_lat, cur_lng):
    """Matches geographic hop to known subsea cable systems."""
    if not prev_city or not cur_city:
        return None
    pc = prev_city.lower().replace(" ", "")
    cc = cur_city.lower().replace(" ", "")
    key = (pc, cc)
    if key in SUBMARINE_CABLES:
        return {"cable": SUBMARINE_CABLES[key], "landing_a": prev_city, "landing_b": cur_city}
    # Fallback: check ocean-spanning distance
    if None not in (prev_lat, prev_lng, cur_lat, cur_lng):
        d = _haversine(prev_lat, prev_lng, cur_lat, cur_lng)
        if d > 2500:
            for (a, b), cable in SUBMARINE_CABLES.items():
                if a in pc or a in cc or b in pc or b in cc or \
                   pc in a or pc in b or cc in a or cc in b:
                    return {"cable": cable, "landing_a": prev_city, "landing_b": cur_city}
            if d > 4000:
                return {"cable": "Likely Subsea / Transoceanic Cable System",
                        "distance_km": round(d),
                        "landing_a": prev_city, "landing_b": cur_city}
    return None

# ── Hardware Hostname Parser ──────────────────────────────────────

IFACE_REGEX = [
    (r'\bae-?(\d+)', 'AE{#}', 'Aggregate Ethernet (LAG Trunk)'),
    (r'\bbe-?(\d+)', 'BE{#}', 'Bundle-Ether (LAG Trunk)'),
    (r'\bxe-([\d/]+)', 'XE-{g}', '10-Gigabit Ethernet'),
    (r'\bge-([\d/]+)', 'GE-{g}', '1-Gigabit Ethernet'),
    (r'\bte-([\d/]+)', 'TE-{g}', '10-Gigabit Ethernet'),
    (r'\bet-([\d/]+)', 'ET-{g}', '100-Gigabit Ethernet'),
    (r'\bhu(\d+)GigE', 'Hu{g}G', '100-Gigabit Ethernet'),
    (r'\bpo-?(\d+)', 'Po{g}', 'Port-Channel (LAG)'),
    (r'\bvl(\d+)', 'Vl{g}', 'VLAN Subinterface'),
    (r'\blo(\d+)', 'Lo{g}', 'Loopback Interface'),
    (r'\bfx\w*-(\d+/\d+/\d+)', 'Fx{g}', 'Flexible PIC Concentrator'),
    (r'\bse-(\d+/\d+/\d+)', 'SE-{g}', 'Service Interface'),
    (r'\b10g\b', '10G', '10-Gigabit Ethernet'),
    (r'\b100g\b', '100G', '100-Gigabit Ethernet'),
    (r'\b40g\b', '40G', '40-Gigabit Ethernet'),
    (r'\b400g\b', '400G', '400-Gigabit Ethernet'),
]

ROLE_REGEX = [
    (r'\b(cr|core)\d*\.?', 'Core Backbone Router'),
    (r'\b(bb|backbone)', 'Backbone Router'),
    (r'\b(br|border)', 'Border Router'),
    (r'\b(gw|gateway)', 'Gateway Router'),
    (r'\b(pe|edge)\d*\.?', 'Provider Edge Router'),
    (r'\b(ce|cpe)', 'Customer Edge Router'),
    (r'\b(asbr)', 'AS Border Router'),
    (r'\b(rr|reflector)', 'Route Reflector'),
    (r'\b(agg|aggregat)', 'Aggregation Router'),
    (r'\b(access|dslam)', 'Access / DSLAM'),
    (r'\b(spine|leaf)', 'Spine-Leaf DC Fabric'),
]

IATA_CODES = {
    "jkt": "Jakarta (CGK)", "sin": "Singapore (SIN)", "sng": "Singapore (SIN)",
    "lhr": "London (LHR)", "lon": "London", "lgw": "London (LGW)",
    "fra": "Frankfurt (FRA)", "muc": "Munich (MUC)", "ber": "Berlin (BER)",
    "ams": "Amsterdam (AMS)", "rtm": "Rotterdam (RTM)",
    "cdg": "Paris (CDG)", "par": "Paris", "ory": "Paris (ORY)",
    "fco": "Rome (FCO)", "mil": "Milan (MXP)", "mxp": "Milan (MXP)",
    "mad": "Madrid (MAD)", "bcn": "Barcelona (BCN)",
    "jfk": "New York (JFK)", "lga": "New York (LGA)", "ewr": "Newark (EWR)",
    "iad": "Washington DC (IAD)", "dca": "Washington DC (DCA)",
    "sfo": "San Francisco (SFO)", "sjc": "San Jose (SJC)", "lax": "Los Angeles (LAX)",
    "ord": "Chicago (ORD)", "mdw": "Chicago (MDW)",
    "dfw": "Dallas (DFW)", "iah": "Houston (IAH)",
    "atl": "Atlanta (ATL)", "mia": "Miami (MIA)",
    "bos": "Boston (BOS)", "phl": "Philadelphia (PHL)",
    "sea": "Seattle (SEA)", "pdx": "Portland (PDX)",
    "den": "Denver (DEN)", "phx": "Phoenix (PHX)",
    "nrt": "Tokyo (NRT)", "hnd": "Tokyo (HND)", "tyo": "Tokyo",
    "kix": "Osaka (KIX)", "ngo": "Nagoya (NGO)",
    "hkg": "Hong Kong (HKG)", "pek": "Beijing (PEK)", "pvg": "Shanghai (PVG)",
    "icn": "Seoul (ICN)", "gmp": "Seoul (GMP)",
    "syd": "Sydney (SYD)", "mel": "Melbourne (MEL)", "bne": "Brisbane (BNE)",
    "dxb": "Dubai (DXB)", "auh": "Abu Dhabi (AUH)",
    "bom": "Mumbai (BOM)", "del": "Delhi (DEL)",
    "gru": "Sao Paulo (GRU)", "eze": "Buenos Aires (EZE)",
    "jnb": "Johannesburg (JNB)", "cpt": "Cape Town (CPT)",
}

def dissect_hostname(hostname):
    """Extract hardware properties from hostname string."""
    if not hostname:
        return {"iface": None, "iface_type": None, "iface_speed": None,
                "router_role": None, "iata_city": None, "raw_recos": []}
    result = {"iface": None, "iface_type": None, "iface_speed": None,
              "router_role": None, "iata_city": None, "raw_recos": []}
    lower = hostname.lower()

    # Interface detection
    for pattern, label, desc in IFACE_REGEX:
        m = re.search(pattern, lower)
        if m:
            group = m.group(0)
            result["iface"] = group
            result["iface_type"] = desc
            if "100-Gigabit" in desc or "100G" in label:
                result["iface_speed"] = "100G"
            elif "10-Gigabit" in desc or "10G" in label:
                result["iface_speed"] = "10G"
            elif "400-Gigabit" in desc or "400G" in label:
                result["iface_speed"] = "400G"
            elif "40-Gigabit" in desc or "40G" in label:
                result["iface_speed"] = "40G"
            elif "1-Gigabit" in desc:
                result["iface_speed"] = "1G"
            if "LAG" in desc or "Aggregate" in desc or "Bundle" in desc:
                result["iface_speed"] = (result["iface_speed"] or "") + " LAG"
            result["raw_recos"].append(desc)
            break

    # Router role detection
    for pattern, role in ROLE_REGEX:
        if re.search(pattern, lower):
            result["router_role"] = role
            result["raw_recos"].append(role)
            break

    # IATA city code detection
    parts = lower.replace(".", " ").replace("-", " ").split()
    for p in parts:
        if p in IATA_CODES:
            result["iata_city"] = IATA_CODES[p]
            result["raw_recos"].append(f"Physical Gateway: {IATA_CODES[p]}")
            break

    return result

# ── RDAP Allocation Data ──────────────────────────────────────────

RDAP_CACHE = {}

ASN_REGISTRY_DATES = {
    "AS15169": {"allocated": "March 2000", "abuse": "network-abuse@google.com", "registry": "ARIN"},
    "AS13335": {"allocated": "July 2010", "abuse": "abuse@cloudflare.com", "registry": "ARIN"},
    "AS32934": {"allocated": "September 2004", "abuse": "abuse@facebook.com", "registry": "ARIN"},
    "AS54113": {"allocated": "October 2011", "abuse": "abuse@fastly.com", "registry": "ARIN"},
    "AS2914": {"allocated": "January 1999", "abuse": "abuse@ntt.net", "registry": "ARIN"},
    "AS3356": {"allocated": "January 2000", "abuse": "abuse@level3.com", "registry": "ARIN"},
    "AS1299": {"allocated": "October 2001", "abuse": "abuse@telia.com", "registry": "RIPE"},
    "AS3257": {"allocated": "January 2001", "abuse": "abuse@gtt.net", "registry": "RIPE"},
    "AS174": {"allocated": "January 1996", "abuse": "abuse@cogentco.com", "registry": "ARIN"},
    "AS6453": {"allocated": "January 1999", "abuse": "abuse@tatacommunications.com", "registry": "ARIN"},
    "AS6762": {"allocated": "January 1994", "abuse": "abuse@telecomitalia.it", "registry": "RIPE"},
    "AS2856": {"allocated": "September 1996", "abuse": "abuse@bt.com", "registry": "RIPE"},
    "AS3320": {"allocated": "January 1999", "abuse": "abuse@t-online.de", "registry": "RIPE"},
    "AS6830": {"allocated": "January 2001", "abuse": "abuse@libertyglobal.com", "registry": "RIPE"},
    "AS6939": {"allocated": "January 1996", "abuse": "abuse@he.net", "registry": "ARIN"},
    "AS4134": {"allocated": "January 1998", "abuse": "anti-spam@ns.chinanet.cn.net", "registry": "APNIC"},
    "AS4837": {"allocated": "January 1999", "abuse": "abuse@chinaunicom.cn", "registry": "APNIC"},
    "AS9808": {"allocated": "January 2000", "abuse": "abuse@chinamobile.com", "registry": "APNIC"},
    "AS24482": {"allocated": "March 2014", "abuse": "abuse@sggs.com", "registry": "APNIC"},
    "AS45530": {"allocated": "January 2015", "abuse": "abuse@sggsap.com", "registry": "APNIC"},
    "AS59253": {"allocated": "October 2012", "abuse": "abuse@leaseweb.com", "registry": "APNIC"},
    "AS132847": {"allocated": "January 2016", "abuse": "abuse@netsolutions.com", "registry": "APNIC"},
    "AS12876": {"allocated": "September 1999", "abuse": "abuse@online.net", "registry": "RIPE"},
}

def _parse_asn_from_org(org_str):
    """Extract ASN from an org string like 'AS15169 Google LLC'."""
    if not org_str:
        return None
    m = re.search(r'\bAS(\d+)\b', org_str, re.IGNORECASE)
    return f"AS{m.group(1)}" if m else None

def lookup_rdap(asn_hint, org_hint):
    """Return allocation metadata from local cache or RDAP."""
    asn = asn_hint or _parse_asn_from_org(org_hint)
    if asn and asn in ASN_REGISTRY_DATES:
        return ASN_REGISTRY_DATES[asn]
    if asn and asn in RDAP_CACHE:
        return RDAP_CACHE[asn]
    # Default fallback
    return {"allocated": "Pre-RIR era (legacy)", "abuse": "Unspecified", "registry": "Various"}

# ── Geo helpers ───────────────────────────────────────────────────

def _haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ── Main enrichment entry point ───────────────────────────────────

def enrich_hop(hop_ip, hostname, prev_ip, prev_org, prev_city,
               cur_lat, cur_lng, prev_lat, prev_lng,
               cur_org, cur_city, cur_country):
    """Return a combined enrichment dict for a single hop."""
    enrich = {}

    # 1. Hardware dissection (always runs, no API needed)
    hw = dissect_hostname(hostname)
    enrich["iface"] = hw["iface"]
    enrich["iface_type"] = hw["iface_type"]
    enrich["iface_speed"] = hw["iface_speed"]
    enrich["router_role"] = hw["router_role"]
    enrich["iata_city"] = hw["iata_city"]
    enrich["hostname_notes"] = hw["raw_recos"]

    # 2. Interconnect detection
    interconnect = detect_interconnect(prev_org, cur_org, prev_city, cur_city)
    enrich["interconnect"] = interconnect.get("interconnect")
    enrich["interconnect_type"] = interconnect.get("interconnect_type")
    enrich["ixp_options"] = interconnect.get("ixp_options", [])

    # 3. Subsea cable detection
    subsea = detect_submarine_cable(prev_city, cur_city, prev_lat, prev_lng, cur_lat, cur_lng)
    if subsea:
        enrich["submarine_cable"] = subsea.get("cable")
        enrich["submarine_landing_a"] = subsea.get("landing_a")
        enrich["submarine_landing_b"] = subsea.get("landing_b")
    else:
        enrich["submarine_cable"] = None

    # 4. RDAP lookup
    rdap = lookup_rdap(None, cur_org)
    enrich["allocated"] = rdap.get("allocated")
    enrich["abuse_handle"] = rdap.get("abuse")
    enrich["registry"] = rdap.get("registry")

    return enrich
