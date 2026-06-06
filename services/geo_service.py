import re
import socket
import httpx
import math
from time import time

ip_cache = {}

COUNTRY_COORDS = {
    "US": (39.8283, -98.5795), "GB": (55.3781, -3.4360), "DE": (51.1657, 10.4515),
    "FR": (46.6034, 1.8883), "NL": (52.1326, 5.2913), "SE": (60.1282, 18.6435),
    "NO": (60.4720, 8.4689), "DK": (56.2639, 9.5018), "FI": (61.9241, 25.7482),
    "IT": (41.8719, 12.5674), "ES": (40.4637, -3.7492), "CH": (46.8182, 8.2275),
    "BE": (50.8503, 4.3517), "AT": (47.5162, 14.5501), "PL": (51.9194, 19.1451),
    "CZ": (49.8175, 15.4730), "RU": (61.5240, 105.3188), "CN": (35.8617, 104.1954),
    "JP": (36.2048, 138.2529), "KR": (35.9078, 127.7669), "IN": (20.5937, 78.9629),
    "SG": (1.3521, 103.8198), "AU": (-25.2744, 133.7751), "NZ": (-40.9006, 174.8860),
    "CA": (56.1304, -106.3468), "MX": (23.6345, -102.5528), "BR": (-14.2350, -51.9253),
    "AR": (-38.4161, -63.6167), "CL": (-35.6751, -71.5430), "ZA": (-30.5595, 22.9375),
    "NG": (9.0820, 8.6753), "EG": (26.8206, 30.8025), "IL": (31.0461, 34.8516),
    "AE": (23.4241, 53.8478), "SA": (23.8859, 45.0792), "TR": (38.9637, 35.2433),
    "HK": (22.3193, 114.1694), "TW": (23.6978, 120.9605), "TH": (15.8700, 100.9925),
    "VN": (14.0583, 108.2772), "ID": (-0.7893, 113.9213), "PH": (12.8797, 121.7740),
    "MY": (4.2105, 101.9758), "PE": (-9.1900, -75.0152), "CO": (4.5709, -74.2973),
    "IE": (53.4129, -8.2439), "PT": (39.3999, -8.2245), "GR": (39.0742, 21.8243),
    "RO": (45.9432, 24.9668), "UA": (48.3794, 31.1656),
}

KNOWN_IPS = {
    "8.8.8.8": {"lat": 39.03, "lng": -77.5, "org": "Google Public DNS", "isp": "Google LLC", "country": "US"},
    "142.250.80.4": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "157.240.1.35": {"lat": 37.48, "lng": -122.15, "org": "Meta Platforms Inc.", "isp": "Facebook", "country": "US"},
    "151.101.192.81": {"lat": 45.50, "lng": -73.57, "org": "Fastly Inc.", "isp": "Fastly", "country": "CA"},
    "39.156.66.10": {"lat": 39.91, "lng": 116.40, "org": "China Mobile", "isp": "China Mobile", "country": "CN"},
}

DOMAIN_COORDS = {
    "google.com": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "facebook.com": {"lat": 37.48, "lng": -122.15, "org": "Meta Platforms Inc.", "isp": "Facebook", "country": "US"},
    "bbc.co.uk": {"lat": 51.51, "lng": -0.13, "org": "BBC", "isp": "BBC", "country": "GB"},
    "baidu.com": {"lat": 39.91, "lng": 116.40, "org": "Baidu", "isp": "Baidu", "country": "CN"},
    "mercadolibre.com.ar": {"lat": -34.60, "lng": -58.38, "org": "Mercado Libre", "isp": "Mercado Libre", "country": "AR"},
    "senaperdiana.com": {"lat": -6.21, "lng": 106.85, "org": "GitHub Pages", "isp": "GitHub", "country": "ID"},
    "biznetnetworks.com": {"lat": -6.23, "lng": 106.86, "org": "Biznet Networks", "isp": "Biznet", "country": "ID"},
    "abc.net.au": {"lat": -33.87, "lng": 151.21, "org": "ABC Australia", "isp": "ABC", "country": "AU"},
}

def _ip_prefix(ip):
    try:
        return ".".join(ip.split(".")[:2])
    except Exception:
        return None

KNOWN_SUBNETS = {
    "142.251": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "142.250": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "74.125": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "172.253": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "172.217": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "216.239": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "216.58": {"lat": 37.42, "lng": -122.08, "org": "Google LLC", "isp": "Google", "country": "US"},
    "157.240": {"lat": 37.48, "lng": -122.15, "org": "Meta Platforms Inc.", "isp": "Facebook", "country": "US"},
    "151.101": {"lat": 45.50, "lng": -73.57, "org": "Fastly Inc.", "isp": "Fastly", "country": "CA"},
    "4.4": {"lat": 21.30, "lng": -157.80, "org": "Lumen / Level 3", "isp": "Lumen", "country": "US"},
    "4.2": {"lat": 21.30, "lng": -157.80, "org": "Lumen / Level 3", "isp": "Lumen", "country": "US"},
    "173.39": {"lat": 37.39, "lng": -122.08, "org": "Cisco / Lumen", "isp": "Cisco", "country": "US"},
    "128.107": {"lat": 37.42, "lng": -122.08, "org": "Cisco Systems", "isp": "Cisco", "country": "US"},
    "27.111": {"lat": -33.87, "lng": 151.21, "org": "Fastly / CDN", "isp": "Fastly", "country": "AU"},
    "39.156": {"lat": 39.91, "lng": 116.40, "org": "China Mobile", "isp": "China Mobile", "country": "CN"},
    "167.253": {"lat": 1.35, "lng": 103.82, "org": "LeaseWeb Asia", "isp": "LeaseWeb", "country": "SG"},
    "23.106": {"lat": 1.35, "lng": 103.82, "org": "LeaseWeb Singapore", "isp": "LeaseWeb", "country": "SG"},
    "31.31": {"lat": 1.35, "lng": 103.82, "org": "LeaseWeb / CDS Networks", "isp": "LeaseWeb", "country": "SG"},
    "192.178": {"lat": 37.42, "lng": -122.08, "org": "Google / YouTube", "isp": "Google", "country": "US"},
}

AIRPORT_CODES = {
    "sjc": "San Jose", "sfo": "San Francisco", "lax": "Los Angeles",
    "sna": "Santa Ana", "san": "San Diego", "pdx": "Portland",
    "sea": "Seattle", "den": "Denver", "ord": "Chicago",
    "dfw": "Dallas", "hou": "Houston", "mia": "Miami",
    "atl": "Atlanta", "jfk": "New York", "lga": "New York",
    "ewr": "Newark", "bwi": "Baltimore", "iad": "Washington DC",
    "bos": "Boston", "phl": "Philadelphia", "pit": "Pittsburgh",
    "stl": "St. Louis", "msp": "Minneapolis", "dtw": "Detroit",
    "cle": "Cleveland", "cvg": "Cincinnati", "ind": "Indianapolis",
    "bna": "Nashville", "rdu": "Raleigh", "clt": "Charlotte",
    "tpa": "Tampa", "fll": "Fort Lauderdale", "msy": "New Orleans",
    "phx": "Phoenix", "las": "Las Vegas", "lhr": "London",
    "fra": "Frankfurt", "cdg": "Paris", "ams": "Amsterdam",
    "fco": "Rome", "mad": "Madrid", "bcn": "Barcelona",
    "zrh": "Zurich", "muc": "Munich", "hnd": "Tokyo",
    "nrt": "Tokyo", "hkg": "Hong Kong", "sin": "Singapore",
    "icn": "Seoul", "pek": "Beijing", "pvg": "Shanghai",
    "syd": "Sydney", "gru": "Sao Paulo", "eze": "Buenos Aires",
    "jnb": "Johannesburg", "dxb": "Dubai", "lon": "London",
    "par": "Paris", "tok": "Tokyo",
}

CITY_COORDS = {
    "honolulu": (21.3, -157.8), "maui": (20.8, -156.3), "hilo": (19.7, -155.1),
    "losangeles": (34.0, -118.2), "la": (34.0, -118.2), "oakland": (37.8, -122.2),
    "paloalto": (37.4, -122.1), "sanjose": (37.3, -121.9), "sanfrancisco": (37.8, -122.4),
    "sacramento": (38.6, -121.5), "sandiego": (32.7, -117.2), "seattle": (47.6, -122.3),
    "portland": (45.5, -122.7), "lasvegas": (36.2, -115.1), "phoenix": (33.4, -112.0),
    "denver": (39.7, -105.0), "dallas": (32.8, -96.8), "houston": (29.8, -95.4),
    "austin": (30.3, -97.7), "sanantonio": (29.4, -98.5), "chicago": (41.9, -87.6),
    "detroit": (42.3, -83.0), "minneapolis": (45.0, -93.3), "stlouis": (38.6, -90.2),
    "nashville": (36.2, -86.8), "atlanta": (33.7, -84.4), "miami": (25.8, -80.2),
    "tampa": (27.9, -82.5), "orlando": (28.5, -81.4), "charlotte": (35.2, -80.8),
    "raleigh": (35.8, -78.6), "washington": (38.9, -77.0), "baltimore": (39.3, -76.6),
    "philadelphia": (40.0, -75.2), "newyork": (40.7, -74.0), "newark": (40.7, -74.2),
    "boston": (42.4, -71.1), "london": (51.5, -0.1), "paris": (48.9, 2.3),
    "frankfurt": (50.1, 8.7), "amsterdam": (52.4, 4.9), "brussels": (50.8, 4.4),
    "zurich": (47.4, 8.5), "milan": (45.5, 9.2), "rome": (41.9, 12.5),
    "madrid": (40.4, -3.7), "barcelona": (41.4, 2.2), "stockholm": (59.3, 18.1),
    "oslo": (59.9, 10.8), "copenhagen": (55.7, 12.6), "helsinki": (60.2, 24.9),
    "warsaw": (52.2, 21.0), "prague": (50.1, 14.4), "vienna": (48.2, 16.4),
    "munich": (48.1, 11.6), "dublin": (53.3, -6.3), "edinburgh": (56.0, -3.2),
    "manchester": (53.5, -2.2), "moscow": (55.8, 37.6), "stpetersburg": (59.9, 30.3),
    "tokyo": (35.7, 139.7), "osaka": (34.7, 135.5), "nagoya": (35.2, 136.9),
    "seoul": (37.6, 127.0), "busan": (35.2, 129.1), "beijing": (39.9, 116.4),
    "shanghai": (31.2, 121.5), "guangzhou": (23.1, 113.3), "shenzhen": (22.5, 114.1),
    "hongkong": (22.3, 114.2), "singapore": (1.4, 103.8), "kualalumpur": (3.1, 101.7),
    "bangkok": (13.8, 100.5), "hanoi": (21.0, 105.9), "hochiminh": (10.8, 106.7),
    "jakarta": (-6.2, 106.8), "manila": (14.6, 121.0), "taipei": (25.0, 121.5),
    "mumbai": (19.1, 72.9), "delhi": (28.6, 77.2), "bangalore": (12.9, 77.6),
    "chennai": (13.1, 80.3), "hyderabad": (17.4, 78.5), "sydney": (-33.9, 151.2),
    "melbourne": (-37.8, 145.0), "brisbane": (-27.5, 153.0), "perth": (-31.9, 115.9),
    "auckland": (-36.8, 174.8), "saopaulo": (-23.5, -46.6), "riodejaneiro": (-22.9, -43.2),
    "buenosaires": (-34.6, -58.4), "santiago": (-33.5, -70.7), "lima": (-12.0, -77.0),
    "bogota": (4.7, -74.1), "mexicocity": (19.4, -99.1), "toronto": (43.7, -79.4),
    "vancouver": (49.3, -123.1), "montreal": (45.5, -73.6), "johannesburg": (-26.2, 28.0),
    "capetown": (-33.9, 18.4), "dubai": (25.2, 55.3), "doha": (25.3, 51.5),
    "istanbul": (41.0, 28.9), "telaviv": (32.1, 34.8), "riyadh": (24.7, 46.7),
}

IATA_COORDS = {
    "cgk": (-6.125, 106.656), "sin": (1.359, 103.989), "lhr": (51.470, -0.454),
    "fra": (50.037, 8.562), "ams": (52.310, 4.768), "nrt": (35.765, 140.385),
    "hnd": (35.553, 139.781), "hkg": (22.308, 113.918), "jfk": (40.641, -73.778),
    "sfo": (37.621, -122.379), "sjc": (37.363, -121.929), "lax": (33.942, -118.408),
    "ord": (41.974, -87.907), "dfw": (32.896, -97.037), "iah": (29.990, -95.336),
    "atl": (33.640, -84.427), "mia": (25.795, -80.290), "bos": (42.366, -71.025),
    "phl": (39.874, -75.242), "sea": (47.450, -122.312), "pdx": (45.589, -122.595),
    "den": (39.856, -104.676), "phx": (33.437, -112.008), "las": (36.084, -115.154),
    "iad": (38.953, -77.456), "dca": (38.852, -77.038), "ewr": (40.690, -74.174),
    "lga": (40.777, -73.873), "muc": (48.354, 11.791), "cdg": (49.009, 2.559),
    "fco": (41.800, 12.253), "mad": (40.494, -3.567), "bcn": (41.297, 2.078),
    "zrh": (47.465, 8.549), "syd": (-33.946, 151.177), "mel": (-37.673, 144.843),
    "bne": (-27.384, 153.117), "per": (-31.938, 115.967), "dxb": (25.253, 55.365),
    "auh": (24.433, 54.651), "pek": (40.080, 116.585), "pvg": (31.144, 121.805),
    "icn": (37.460, 126.440), "kix": (34.435, 135.244), "tyo": (35.682, 139.760),
    "bom": (19.089, 72.868), "del": (28.557, 77.103), "gru": (-23.431, -46.470),
    "jnb": (-26.134, 28.242), "cpt": (-33.965, 18.602), "gig": (-22.809, -43.251),
    "doh": (25.273, 51.608), "ist": (41.261, 28.742), "sgn": (10.819, 106.659),
    "mnl": (14.509, 121.014), "bkk": (13.690, 100.750), "kul": (2.745, 101.708),
    "cnx": (18.771, 98.970), "dps": (-8.748, 115.167), "ngo": (34.858, 136.805),
    "akl": (-37.008, 174.792), "tpe": (25.080, 121.232), "scl": (-33.393, -70.786),
    "eze": (-34.822, -58.536), "lim": (-12.022, -77.114), "mex": (19.436, -99.072),
    "yow": (45.322, -75.669), "yul": (45.471, -73.741), "yvr": (49.195, -123.179),
    "yyz": (43.677, -79.631), "jkt": (-6.125, 106.656), "sng": (1.359, 103.989),
    "lon": (51.470, -0.454), "par": (48.856, 2.352), "nyc": (40.713, -74.006),
    "tyo": (35.682, 139.760), "waw": (52.166, 20.967), "prg": (50.075, 14.438),
    "cph": (55.618, 12.656), "osl": (60.194, 11.100), "arn": (59.652, 17.919),
    "hel": (60.318, 24.963), "bru": (50.901, 4.484), "vie": (48.111, 16.570),
}

IXP_CITY_SNAP = {
    "sg1": (1.309, 103.842), "sg2": (1.309, 103.842), "sg3": (1.309, 103.842),
    "singapore": (1.352, 103.820), "sgix": (1.352, 103.820),
    "jakarta": (-6.209, 106.847), "jk1": (-6.209, 106.847),
    "openixp": (-6.209, 106.847), "iix": (-6.209, 106.847),
    "hong kong": (22.319, 114.169), "hk1": (22.319, 114.169), "hkix": (22.319, 114.169),
    "tokyo": (35.676, 139.764), "ty2": (35.676, 139.764), "ty3": (35.676, 139.764),
    "london": (51.507, -0.128), "lon1": (51.507, -0.128), "linx": (51.507, -0.128),
    "ld4": (51.507, -0.128), "ld5": (51.507, -0.128), "lonap": (51.507, -0.128),
    "frankfurt": (50.111, 8.682), "fr2": (50.111, 8.682), "fr5": (50.111, 8.682),
    "de-cix": (50.111, 8.682),
    "amsterdam": (52.368, 4.904), "ams-ix": (52.368, 4.904),
    "new york": (40.713, -74.006), "ny1": (40.713, -74.006), "ny2": (40.713, -74.006),
    "sanjose": (37.336, -121.891), "sv1": (37.336, -121.891), "sv5": (37.336, -121.891),
    "losangeles": (33.943, -118.408), "la1": (33.943, -118.408),
    "ashburn": (39.044, -77.488), "dc2": (39.044, -77.488), "dc6": (39.044, -77.488),
    "sydney": (-33.869, 151.210), "sy3": (-33.869, 151.210),
    "mumbai": (19.076, 72.878), "dubai": (25.205, 55.271),
    "shanghai": (31.230, 121.474), "beijing": (39.904, 116.407),
    "zurich": (47.377, 8.540), "paris": (48.857, 2.352),
    "sao paulo": (-23.550, -46.633), "buenos aires": (-34.604, -58.382),
    "seoul": (37.566, 126.978), "osaka": (34.694, 135.502),
    "manila": (14.600, 120.984), "bangkok": (13.757, 100.502),
    "kuala lumpur": (3.139, 101.687), "taipei": (25.033, 121.565),
    "ho chi minh": (10.823, 106.630),
}

def ixp_snap_coords(interconnect_text, cur_lat, cur_lng):
    if not interconnect_text:
        return (cur_lat, cur_lng)
    lower = interconnect_text.lower()
    for keyword, (lat, lng) in IXP_CITY_SNAP.items():
        if keyword in lower:
            return (lat, lng)
    return (cur_lat, cur_lng)

NETWORK_KEYWORDS = {
    "bb": "Backbone Router", "gw": "Gateway Router",
    "cr": "Core Router", "br": "Border Router",
    "mr": "Metro Router", "ar": "Access Router",
    "asbr": "AS Border Router", "rr": "Route Reflector",
    "pe": "Provider Edge", "ce": "Customer Edge",
    "aggr": "Aggregation Switch", "dist": "Distribution Switch",
}

INTERFACE_PATTERNS = [
    (r'ae-(\d+)', lambda m: f"Aggregate Ethernet #{m.group(1)}"),
    (r'xe-(\d+/\d+/\d+)', lambda m: f"10GigE {m.group(1)}"),
    (r'ge-(\d+/\d+/\d+)', lambda m: f"GigabitEthernet {m.group(1)}"),
    (r'te-(\d+/\d+/\d+)', lambda m: f"10GigE {m.group(1)}"),
    (r'et-(\d+/\d+/\d+)', lambda m: f"100GigE {m.group(1)}"),
    (r'be(\d+)', lambda m: f"Bundle-Ether #{m.group(1)}"),
    (r'Po(\d+)', lambda m: f"Port-Channel #{m.group(1)}"),
]

INFRA_LABELS = {
    "ntt": "NTT Communications — Global IP Network",
    "level3": "Level 3 / Lumen — Tier 1 Backbone",
    "cogent": "Cogent Communications — Tier 1 Backbone",
    "gblx": "Global Crossing / Level 3",
    "telstra": "Telstra — Australian Backbone",
    "singtel": "Singtel — Singapore Backbone",
    "pccw": "PCCW Global — Hong Kong Backbone",
    "tatacomm": "Tata Communications — Global Backbone",
    "decix": "DE-CIX — Frankfurt Internet Exchange",
    "amix": "AMS-IX — Amsterdam Internet Exchange",
    "linx": "LINX — London Internet Exchange",
    "equinix": "Equinix — Global Data Center / IX",
    "google": "Google — Private Network Infrastructure",
    "facebook": "Meta — Private WAN Infrastructure",
    "cloudflare": "Cloudflare — Global Edge Network",
    "akamai": "Akamai — CDN Edge Node",
    "fastly": "Fastly — CDN Edge Node",
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

_api_failures = 0

PRIVATE_RANGES = [
    ("10.0.0.0", "10.255.255.255"),
    ("172.16.0.0", "172.31.255.255"),
    ("192.168.0.0", "192.168.255.255"),
    ("100.64.0.0", "100.127.255.255"),
    ("198.18.0.0", "198.19.255.255"),
    ("169.254.0.0", "169.254.255.255"),
]

def _ip_to_int(ip):
    parts = ip.split(".")
    return int(parts[0]) * 16777216 + int(parts[1]) * 65536 + int(parts[2]) * 256 + int(parts[3])

def _is_private(ip):
    try:
        n = _ip_to_int(ip)
        for lo, hi in PRIVATE_RANGES:
            if _ip_to_int(lo) <= n <= _ip_to_int(hi):
                return True
    except Exception:
        pass
    return False

def _subnet_label(ip):
    prefix = _ip_prefix(ip)
    if prefix and prefix in KNOWN_SUBNETS:
        return KNOWN_SUBNETS[prefix].get("org", "Unknown ISP")
    octets = ip.split(".")
    if len(octets) >= 2:
        first = int(octets[0])
        # Speed-of-light ISP inference from known /8 allocations
        if first == 4 or first == 8: return "Lumen / Level 3"
        if first == 12: return "AT&T Services"
        if first == 17: return "Apple Inc."
        if first in (23, 103, 180): return "LeaseWeb / CDN Backbone"
        if first in (31, 38, 154): return "Cogent / PSI Net"
        if first in (64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79): return "ARIN Legacy ISP"
        if first in (202, 203, 210, 211, 218, 219, 220, 221, 222, 223): return "Asia-Pacific Backbone"
        return f"Network {octets[0]}.{octets[1]}.x.x"
    return "Unknown ISP"

async def geolocate_ip(ip):
    global _api_failures
    if ip in ip_cache:
        entry = ip_cache[ip]
        if time() - entry["ts"] < 3600:
            return entry["data"]
    if _is_private(ip):
        result = {"lat": 0, "lng": 0, "org": "Local Network", "isp": "Private", "country": "US"}
        ip_cache[ip] = {"data": result, "ts": time()}
        return result
    if ip in KNOWN_IPS:
        result = dict(KNOWN_IPS[ip])
        ip_cache[ip] = {"data": result, "ts": time()}
        return result
    prefix = _ip_prefix(ip)
    if prefix and prefix in KNOWN_SUBNETS:
        result = dict(KNOWN_SUBNETS[prefix])
        result["org"] = result.get("org", "Unknown")
        result["isp"] = result.get("isp", "")
        result["country"] = result.get("country", "US")
        ip_cache[ip] = {"data": result, "ts": time()}
        return result
    if _api_failures >= 5:
        label = _subnet_label(ip)
        result = {"lat": 0, "lng": 0, "org": label, "isp": label, "country": ""}
        ip_cache[ip] = {"data": result, "ts": time()}
        return result
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,message,lat,lon,org,isp,country,countryCode,query"
            )
            data = resp.json()
    except Exception:
        _api_failures += 1
        label = _subnet_label(ip)
        return {"lat": 0, "lng": 0, "org": label, "isp": label, "country": ""}
    if data.get("status") != "success":
        _api_failures += 1
        label = _subnet_label(ip)
        return {"lat": 0, "lng": 0, "org": label, "isp": label, "country": ""}
    _api_failures = 0
    result = {
        "lat": data["lat"],
        "lng": data["lon"],
        "org": data.get("org", "") or "",
        "isp": data.get("isp", "") or "",
        "country": data.get("countryCode", "") or "US",
    }
    ip_cache[ip] = {"data": result, "ts": time()}
    return result

def reverse_dns(ip):
    try:
        resolved = socket.gethostbyaddr(ip)
        return resolved[0] if isinstance(resolved, tuple) else resolved
    except Exception:
        return None

def geolocate_from_hostname(hostname):
    if not hostname:
        return None
    lower = hostname.lower().replace("-", " ").replace(".", " ").replace("_", " ")
    parts = lower.split()
    # ── 1. Check IATA codes first (most precise) ──
    for p in parts:
        code = p.replace("01", "").replace("02", "").replace("03", "").replace("04", "").replace("1", "").replace("2", "").replace("3", "")
        if code in IATA_COORDS:
            lat, lng = IATA_COORDS[code]
            city = code.upper()
            if code in AIRPORT_CODES:
                city = AIRPORT_CODES[code]
            return {"lat": lat, "lng": lng, "city": city, "iata_code": code.upper()}
    # ── 2. Check full city names in full hostname ──
    for word, (lat, lng) in CITY_COORDS.items():
        if word in lower:
            return {"lat": lat, "lng": lng, "city": word.title()}
    # ── 3. Check word prefixes/suffixes ──
    for seg in parts:
        for word, (lat, lng) in CITY_COORDS.items():
            if seg.startswith(word) or seg.endswith(word):
                return {"lat": lat, "lng": lng, "city": word.title()}
    return None

def parse_hostname(hostname):
    if not hostname:
        return {"labels": [], "city": None, "country": None, "network_role": None, "interface": None}
    labels = []
    city = None
    country = None
    network_role = None
    interface = None
    parts = hostname.lower().replace(".", " ").replace("-", " ").split()
    for i, p in enumerate(parts):
        if p in INFRA_LABELS:
            labels.append(INFRA_LABELS[p])
            continue
        if p in AIRPORT_CODES:
            city = AIRPORT_CODES[p]
            if i + 1 < len(parts) and parts[i + 1] in ("ca", "us", "ny", "tx", "fl", "il", "va", "wa", "or", "co", "ga", "ma", "pa", "md", "az", "nv", "mn", "oh", "nc", "sc", "la", "mo"):
                continue
            labels.append(f"Location: {AIRPORT_CODES[p]}")
            continue
        if p in NETWORK_KEYWORDS:
            network_role = NETWORK_KEYWORDS[p]
            labels.append(f"Role: {NETWORK_KEYWORDS[p]}")
            continue
    for pattern, handler in INTERFACE_PATTERNS:
        m = re.search(pattern, hostname.lower())
        if m:
            interface = handler(m)
            labels.append(f"Interface: {interface}")
            break
    return {"labels": labels, "city": city, "country": country, "network_role": network_role, "interface": interface}

def smooth_coordinates(prev, cur, nxt, rtt_ms):
    if prev is None or nxt is None or rtt_ms is None:
        return (cur[0], cur[1])
    d_prev = haversine(prev[0], prev[1], cur[0], cur[1])
    d_next = haversine(cur[0], cur[1], nxt[0], nxt[1])
    if rtt_ms > 0:
        # Speed of light in fiber ≈ 200 km/ms; max one-way = 100 * rtt_ms km
        if d_prev > rtt_ms * 100 or d_next > rtt_ms * 100:
            mid_lat = (prev[0] + nxt[0]) / 2
            mid_lng = (prev[1] + nxt[1]) / 2
            return (mid_lat, mid_lng)
    return (cur[0], cur[1])
