import os
import socket
import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

HOST_CFG = os.getenv("APP_HOST", "0.0.0.0")
PORT = int(os.getenv("APP_PORT", 8004))
MOCK_PUBLIC_IP = os.getenv("MOCK_PUBLIC_IP", "8.8.8.8")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
MAX_HOPS = int(os.getenv("TRACEROUTE_MAX_HOPS", 30))

HOST_ORIGIN = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global HOST_ORIGIN
    import httpx
    # Try ip-api.com first (HTTP, no key needed)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://ip-api.com/json/?fields=lat,lon,city,country,countryCode,query")
            if r.status_code == 200:
                d = r.json()
                HOST_ORIGIN = {
                    "lat": float(d["lat"]), "lng": float(d["lon"]),
                    "city": d.get("city", ""), "country": d.get("countryCode", ""),
                    "ip": d.get("query", ""),
                }
    except Exception:
        pass
    # Fallback: ipapi.co
    if not HOST_ORIGIN:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://ipapi.co/json/")
                if r.status_code == 200:
                    d = r.json()
                    HOST_ORIGIN = {
                        "lat": float(d.get("latitude", 0)), "lng": float(d.get("longitude", 0)),
                        "city": d.get("city", ""), "country": d.get("country_code", ""),
                        "ip": d.get("ip", ""),
                    }
        except Exception:
            pass
    # Final fallback: Singapore safe default
    if not HOST_ORIGIN:
        HOST_ORIGIN = {"lat": 1.3521, "lng": 103.8198, "city": "Singapore", "country": "SG", "ip": "unknown"}
    yield

app = FastAPI(title="Traceroute Visualizer", lifespan=lifespan)

PRESET_TARGETS = [
    {"label": "Google LLC (USA Core)", "domain": "google.com"},
    {"label": "Facebook / Meta (Europe Hub)", "domain": "facebook.com"},
    {"label": "BBC News (UK Backbone)", "domain": "bbc.co.uk"},
    {"label": "Baidu (Asia / China)", "domain": "baidu.com"},
    {"label": "Mercado Libre (South America)", "domain": "mercadolibre.com.ar"},
    {"label": "Biznet Networks (Indonesia Backbone)", "domain": "biznetnetworks.com"},
    {"label": "ABC Australia", "domain": "abc.net.au"},
    {"label": "Sena Perdiana (GitHub Pages)", "domain": "senaperdiana.com"},
]

from services.traceroute_service import run_trace
from services.geo_service import geolocate_ip, geolocate_from_hostname, parse_hostname, DOMAIN_COORDS, ixp_snap_coords
from services.latency_service import haversine, compound_rtt, interpolate_path
from services.enrichment_service import enrich_hop

# ── Concurrency gate: max 3 simultaneous traces ──
TRACE_SEMAPHORE = asyncio.Semaphore(3)

# ── MaxMind GeoLite2 City reader (memory-mapped mock until .mmdb available) ──
def _geoip_lookup(ip):
    """Stub: returns mock coordinates until geoip2 + .mmdb file is deployed.
       Replace with: reader.city(ip).location.latitude / longitude"""
    return {"lat": 0.0, "lng": 0.0, "city": "Unknown", "country": "??", "org": "Unknown"}

@app.middleware("http")
async def resolve_client_ip(request: Request, call_next):
    real_ip = request.headers.get("CF-Connecting-IP")
    if not real_ip:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            real_ip = forwarded.split(",")[0].strip()
    if not real_ip:
        real_ip = MOCK_PUBLIC_IP
    request.state.real_ip = real_ip
    return await call_next(request)

@app.get("/api/presets")
async def get_presets():
    return PRESET_TARGETS

@app.get("/api/resolve")
async def resolve_target(target: str):
    try:
        ip = socket.gethostbyname(target)
        return {"domain": target, "ip": ip}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

async def hop_stream(target_domain: str):
    src_lat = HOST_ORIGIN["lat"]
    src_lng = HOST_ORIGIN["lng"]

    # ── Concurrency gate: wait for a trace slot ──
    if TRACE_SEMAPHORE.locked():
        yield f"data: {json.dumps({'status': 'waiting_in_queue'})}\n\n"
    await TRACE_SEMAPHORE.acquire()
    # ── Emit origin as first event ──
    yield f"data: {json.dumps({'type': 'source', 'lat': src_lat, 'lng': src_lng, 'city': HOST_ORIGIN.get('city',''), 'country': HOST_ORIGIN.get('country',''), 'origin_ip': HOST_ORIGIN.get('ip','')})}\n\n"

    try:
        target_ip = socket.gethostbyname(target_domain)
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        TRACE_SEMAPHORE.release()
        return

    target_geo = await geolocate_ip(target_ip)
    if target_domain in DOMAIN_COORDS:
        target_geo = dict(DOMAIN_COORDS[target_domain])
    elif target_geo.get("lat", 0) == 0 and target_domain in DOMAIN_COORDS:
        target_geo = dict(DOMAIN_COORDS[target_domain])
    tgt_lat = target_geo.get("lat", 0) or 0
    tgt_lng = target_geo.get("lng", 0) or 0

    yield f"data: {json.dumps({'type': 'meta', 'target_ip': target_ip, 'target_domain': target_domain, 'origin_city': HOST_ORIGIN.get('city','')})}\n\n"

    prev_lat, prev_lng = src_lat, src_lng
    prev_org, prev_city, prev_ip = "Origin", HOST_ORIGIN.get("city", ""), None
    cumulative_rtt = 0.0
    hop_coords = [(src_lat, src_lng)]
    total_expected = MAX_HOPS

    async for hop in run_trace(target_domain, MAX_HOPS):
        hnum = hop["hop"] or 1

        if hop["timeout"]:
            frac = hnum / total_expected
            ilat = src_lat + (tgt_lat - src_lat) * frac
            ilng = src_lng + (tgt_lng - src_lng) * frac
            hop_coords.append((ilat, ilng))
            prev_lat, prev_lng = ilat, ilng
            yield f"data: {json.dumps({'hop': hnum, 'timeout': True, 'rtt_ms': None, 'lat': round(ilat,4), 'lng': round(ilng,4), 'asn': None, 'mpls_label': None, 'icmp_error': None})}\n\n"
            continue

        geo = {"lat": 0, "lng": 0, "org": "Unknown", "isp": "Unknown", "country": "??"}
        if hop["ip"]:
            geo = await geolocate_ip(hop["ip"])
        lat, lng = geo["lat"], geo["lng"]

        # ── Async reverse DNS (non-blocking, PTR record) ──
        hname = None
        if hop["ip"]:
            try:
                resolved = await asyncio.wait_for(
                    asyncio.to_thread(socket.gethostbyaddr, hop["ip"]),
                    timeout=1.5,
                )
                hname = resolved[0] if isinstance(resolved, tuple) else resolved
            except Exception:
                pass

        # Override generic labels
        org = (geo.get("org") or "")
        if org.startswith("Network ") or org in ("Unknown ISP", "Unknown", "Unavailable", ""):
            # No hostname from traceroute (-n flag), skip hostname override
            pass

        if lng == 0 and lat == 0:
            host_fallback = None
            if hname:
                host_fallback = geolocate_from_hostname(hname)
            if host_fallback:
                lat, lng = host_fallback["lat"], host_fallback["lng"]
                if host_fallback.get("city") and (not geo.get("org") or geo.get("org") in ("Unknown", "Unavailable", "")):
                    geo["org"] = host_fallback["city"]

        if lat == 0 and lng == 0:
            frac = hnum / total_expected
            lat = src_lat + (tgt_lat - src_lat) * frac
            lng = src_lng + (tgt_lng - src_lng) * frac

        # Speed-of-light / anycast validation
        rtt_raw = hop["rtt_ms"] or 0
        if rtt_raw > 0 and prev_lat and prev_lng:
            if haversine(prev_lat, prev_lng, lat, lng) > rtt_raw * 100:
                frac = hnum / total_expected
                lat = src_lat + (tgt_lat - src_lat) * frac
                lng = src_lng + (tgt_lng - src_lng) * frac
            elif haversine(prev_lat, prev_lng, lat, lng) > 5000 and rtt_raw < 30:
                lat = 0
                lng = 0

        if lat == 0 and lng == 0:
            frac = hnum / total_expected
            lat = src_lat + (tgt_lat - src_lat) * frac
            lng = src_lng + (tgt_lng - src_lng) * frac

        crtt = compound_rtt(prev_lat, prev_lng, lat, lng, rtt_raw)
        cumulative_rtt += crtt
        hop_coords.append((lat, lng))
        prev_lat, prev_lng = lat, lng

        parsed = parse_hostname(hname)

        cur_org = geo.get("org", "")
        cur_city = parsed.get("city") or ""
        enrichment = enrich_hop(
            hop_ip=hop.get("ip"),
            hostname=hname,
            prev_ip=prev_ip,
            prev_org=prev_org,
            prev_city=prev_city,
            cur_lat=lat, cur_lng=lng,
            prev_lat=(prev_lat if prev_lat and prev_lat != lat else src_lat),
            prev_lng=(prev_lng if prev_lng and prev_lng != lng else src_lng),
            cur_org=cur_org,
            cur_city=cur_city,
            cur_country=geo.get("country", ""),
        )
        prev_ip = hop.get("ip")
        prev_org = cur_org or prev_org
        prev_city = cur_city or prev_city

        # IXP coordinate snap
        interconnect_name = enrichment.get("interconnect", "")
        if interconnect_name and "Equinix" in interconnect_name or "IXP" in (enrichment.get("interconnect_type") or ""):
            snap_lat, snap_lng = ixp_snap_coords(interconnect_name, lat, lng)
            if (snap_lat, snap_lng) != (lat, lng):
                lat, lng = snap_lat, snap_lng
                hop_coords[-1] = (lat, lng)
                prev_lat, prev_lng = lat, lng

        # Local Latency Gate: snap sub-5ms internal hops to origin to prevent
        # GeoIP from plotting internal switches in wrong countries (e.g. Batam).
        if hop["rtt_ms"] and hop["rtt_ms"] < 5:
            lat, lng = src_lat, src_lng
            hop_coords[-1] = (lat, lng)
            prev_lat, prev_lng = lat, lng

        # ── Latency-based location validation ──
        # If cumulative RTT > 35ms, strip ISP-registration location overrides
        # and replace with actual geographic context for subsea transit hops.
        if cumulative_rtt > 35:
            parsed_labels = list(parsed.get("labels") or [])
            # Remove "Location:" labels from corporate BGP records
            parsed_labels = [l for l in parsed_labels if not l.startswith("Location:")]
            # Determine actual geographic region from coordinates
            transit_label = None
            if enrichment.get("submarine_cable"):
                if -10 < lat < 10 and 40 < lng < 80:
                    transit_label = "Western Indian Ocean Transit"
                elif -15 < lat < 0 and 30 < lng < 50:
                    transit_label = "Mozambique Channel Subsea Segment"
                elif 20 < lat < 40 and -30 < lng < 10:
                    transit_label = "Mid-Atlantic Subsea Crossing"
                elif 20 < lat < 40 and 120 < lng < 160:
                    transit_label = "Western Pacific Transit"
                elif 0 < lat < 20 and 55 < lng < 75:
                    transit_label = "Arabian Sea Transit"
                elif -5 < lat < 15 and 95 < lng < 115:
                    transit_label = "Malacca Strait Transit"
                elif 30 < lat < 50 and 0 < lng < 20:
                    transit_label = "Mediterranean Subsea Segment"
                else:
                    transit_label = "Subsea Cable Transit Zone"
            else:
                if lat == 0 and lng == 0:
                    transit_label = None
                elif abs(lat) < 5 and abs(lng) < 5:
                    transit_label = None  # Null Island, already known bad
            if transit_label:
                parsed_labels.insert(0, transit_label)
                enrichment["iata_city"] = None
            else:
                enrichment["iata_city"] = None
        else:
            parsed_labels = parsed.get("labels", [])

        yield f"data: {json.dumps({
            'hop': hnum,
            'ip': hop.get('ip'),
            'lat': round(lat, 4),
            'lng': round(lng, 4),
            'hostname': hname,
            'rtt_ms': round(crtt, 2),
            'rtt_cumulative': round(cumulative_rtt, 2),
            'org': geo.get('org', ''),
            'isp': geo.get('isp', ''),
            'country': geo.get('country', ''),
            'city': parsed.get('city'),
            'network_role': parsed.get('network_role'),
            'interface': parsed.get('interface'),
            'labels': parsed_labels,
            'iface': enrichment.get('iface'),
            'iface_type': enrichment.get('iface_type'),
            'iface_speed': enrichment.get('iface_speed'),
            'router_role': enrichment.get('router_role') or parsed.get('network_role'),
            'iata_city': enrichment.get('iata_city'),
            'hostname_notes': enrichment.get('hostname_notes', []),
            'interconnect': enrichment.get('interconnect'),
            'interconnect_type': enrichment.get('interconnect_type'),
            'submarine_cable': enrichment.get('submarine_cable'),
            'allocated': enrichment.get('allocated'),
            'abuse_handle': enrichment.get('abuse_handle'),
            'registry': enrichment.get('registry'),
            'asn': hop.get('asn'),
            'mpls_label': hop.get('mpls_label'),
            'icmp_error': hop.get('icmp_error'),
            'timeout': False,
        })}\n\n"

    poly_pts = hop_coords.copy()
    if tgt_lat != 0 or tgt_lng != 0:
        poly_pts.append((tgt_lat, tgt_lng))
    interpolated = interpolate_path(poly_pts, segment_km=300)
    yield f"data: {json.dumps({'type': 'target', 'lat': tgt_lat, 'lng': tgt_lng, 'org': target_geo.get('org', target_domain), 'isp': target_geo.get('isp', ''), 'country': target_geo.get('country', ''), 'polyline': [[round(p[0],4), round(p[1],4)] for p in interpolated]})}\n\n"
    yield "data: [DONE]\n\n"
    TRACE_SEMAPHORE.release()

@app.get("/api/trace")
async def trace_stream(request: Request, target: str):
    if not target:
        return JSONResponse(status_code=400, content={"error": "target required"})
    return StreamingResponse(
        hop_stream(target),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST_CFG, port=PORT, reload=(ENVIRONMENT != "production"))
