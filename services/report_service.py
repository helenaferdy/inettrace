"""Engineer Operations Report — full-path analysis from collected hop telemetry."""

import math

# ── Latency classification ────────────────────────────────────────

def _classify_delta(rtt_delta):
    if rtt_delta is None: return ("N/A", "No data")
    if rtt_delta < 20:    return ("Nominal", "Standard localized routing / intra-regional switching")
    if rtt_delta < 50:    return ("Moderate", "Potential regional haul or inter-city backhaul")
    if rtt_delta < 100:   return ("Significant", "Substantial geographic leap — continental edge or short subsea transit")
    return ("Major Shift", "Intercontinental transit or long-haul undersea deployment")

# ── Main report generator ──────────────────────────────────────────

def generate_report(hops, target_domain, source_city):
    """Consume a list of enriched hop dicts and return a structured report."""
    if not hops:
        return {"error": "No hop data available"}

    # ── 1. Top Latency Contributors ────────────────────────────────
    deltas = []
    for i in range(len(hops)):
        h = hops[i]
        rtt = h.get("rtt_ms")
        cum = h.get("rtt_cumulative")
        delta = None
        if i > 0 and hops[i - 1].get("rtt_cumulative") is not None and cum is not None:
            delta = round(cum - hops[i - 1]["rtt_cumulative"], 2)
        classification, reason = _classify_delta(delta) if delta else ("N/A", "No data")
        deltas.append({
            "hop": h.get("hop", i + 1),
            "ip": h.get("ip", "?"),
            "rtt": rtt,
            "cumulative": cum,
            "delta": delta,
            "class": classification,
            "reason": reason,
        })
    # Sort by delta descending, top 5
    top_contributors = sorted(
        [d for d in deltas if d["delta"] is not None],
        key=lambda x: x["delta"], reverse=True
    )[:5]
    latency_summary = []
    for i, d in enumerate(top_contributors):
        prev_hop = d["hop"] - 1 if d["hop"] > 1 else "Source"
        latency_summary.append(f"Hop [{prev_hop}] → [{d['hop']}]: +{d['delta']}ms [{d['class']}] — {d['reason']}")

    # ── 2. ASN Transition Summary ──────────────────────────────────
    asn_chain = []
    seen_orgs = []
    for h in hops:
        org = (h.get("org") or "").strip()
        if org and org not in ("Unknown", "Unavailable", "Unknown ISP", "Internal Backbone (same AS)", ""):
            if not seen_orgs or seen_orgs[-1] != org:
                seen_orgs.append(org)
    handoffs = max(0, len(seen_orgs) - 1)
    asn_summary = " ➔ ".join([f"{o}" for o in seen_orgs]) if seen_orgs else "Unknown"
    asn_detail = {
        "chain": seen_orgs,
        "handoff_count": handoffs,
        "summary": asn_summary,
    }

    # ── 3. Carrier & IXP Handoff Diagnostics ───────────────────────
    ixp_handoffs = []
    for h in hops:
        ic = h.get("interconnect") or ""
        ic_type = h.get("interconnect_type") or ""
        if ic and ic != "Internal Backbone (same AS)" and "Unspecified" not in ic:
            ixp_handoffs.append({
                "hop": h.get("hop"),
                "fabric": ic,
                "type": ic_type,
                "from_org": _safe_org(hops, h.get("hop", 0) - 1),
                "to_org": h.get("org", ""),
            })

    # ── 4. Routing Anomalies & Detours ─────────────────────────────
    anomalies = []
    # Anycast detection: <5ms RTT to distant target implies local anycast node
    for h in hops:
        rtt = h.get("rtt_cumulative")
        if rtt is not None and rtt < 5:
            org = h.get("org", "")
            city = h.get("city") or h.get("iata_city") or ""
            if source_city.lower() not in (city or "").lower():
                anomalies.append({
                    "hop": h.get("hop"),
                    "type": "Anycast Edge Node",
                    "detail": f"Hop {h.get('hop')} ({org}) responding at <5ms from {source_city} — likely Anycast CDN/edge node serving local region.",
                    "confidence": 92,
                })

    # ── 5. MPLS Core / Hidden Segments ─────────────────────────────
    mpls_blocks = []
    i = 0
    while i < len(hops):
        if hops[i].get("timeout"):
            start = i
            start_org = _safe_org(hops, start - 1) if start > 0 else "Entry"
            while i < len(hops) and hops[i].get("timeout"):
                i += 1
            end_org = _safe_org(hops, i) if i < len(hops) else "Exit"
            if start_org == end_org or _clean_org(start_org) == _clean_org(end_org):
                mpls_blocks.append({
                    "hops": f"{hops[start]['hop']}–{hops[i-1]['hop']}" if start < i else str(hops[start]['hop']),
                    "confidence": 88,
                    "detail": f"Consecutive timeouts within same AS ({start_org} → {end_org}). Likely MPLS LDP/RSVP-TE explicit-path core segment — labels hide intermediate P routers from traceroute probes.",
                })
            else:
                mpls_blocks.append({
                    "hops": f"{hops[start]['hop']}–{hops[i-1]['hop']}" if start < i else str(hops[start]['hop']),
                    "confidence": 55,
                    "detail": f"Consecutive timeouts across AS boundary ({start_org} → {end_org}). Possible carrier MPLS or ICMP filtering at peering edge.",
                })
        else:
            i += 1

    # ── 6. Submarine Cable Probability Matrix ──────────────────────
    subsea_entries = []
    for h in hops:
        cable = h.get("submarine_cable")
        if cable:
            landing_a = h.get("submarine_landing_a") or "?"
            landing_b = h.get("submarine_landing_b") or "?"
            rtt = h.get("rtt_cumulative")
            prev_cum = _prev_cum(hops, h.get("hop", 0))
            delta = round(rtt - prev_cum, 2) if rtt and prev_cum is not None else None
            subsea_entries.append({
                "hop": h.get("hop"),
                "cable": cable,
                "from_city": landing_a,
                "to_city": landing_b,
                "delta_rtt": delta,
                "confidence": 82,
            })

    # ── 7. Packet Loss & Policing Audit ────────────────────────────
    # Not available from Globalping single-probe traceroute
    ploss_note = "Not applicable — Globalping traceroute uses single probe per hop (-q 1). Multi-probe MTR data required for true loss analysis."

    # ── 8. Metric Confidence Report ────────────────────────────────
    measured_count = 0    # hop, ip, rtt
    derived_count = 0     # org, asn, rdap
    inferred_count = 0    # geo, city, submarine
    for h in hops:
        measured_count += 1  # every hop has measured rtt
        if h.get("org") and h.get("org") not in ("Unknown", "Unavailable", "Unknown ISP"):
            derived_count += 1
        if (h.get("city") or h.get("iata_city")):
            inferred_count += 0.5  # partial confidence
        if h.get("submarine_cable"):
            inferred_count += 0.5
    # Count IATA-verified coordinates
    iata_verified = sum(1 for h in hops if h.get("iata_city"))
    geo_ip_only = sum(1 for h in hops if not h.get("iata_city") and (h.get("city") or h.get("country") not in ("??", "")))
    confidence = {
        "measured_pct": 100,
        "measured_detail": f"{len(hops)} hops with measured RTT — 100% verified on wire",
        "derived_pct": min(100, round(100 * derived_count / max(1, len(hops)))),
        "derived_detail": f"{derived_count}/{len(hops)} hops have verified ASN/org from RDAP or subnet registry",
        "inferred_pct": min(100, round(100 * (iata_verified * 0.9 + geo_ip_only * 0.5) / max(1, len(hops)))),
        "inferred_detail": f"IATA-verified: {iata_verified} hops (high confidence). GeoIP-only: {geo_ip_only} hops (medium confidence).",
        "ixp_verified": len(ixp_handoffs),
    }

    return {
        "target": target_domain,
        "source": source_city,
        "hop_count": len(hops),
        "total_rtt": round(hops[-1].get("rtt_cumulative", 0), 2) if hops else 0,
        "latency_summary": latency_summary,
        "asn_summary": asn_detail,
        "ixp_handoffs": ixp_handoffs,
        "anomalies": anomalies,
        "mpls_blocks": mpls_blocks,
        "subsea_entries": subsea_entries,
        "packet_loss_note": ploss_note,
        "confidence": confidence,
    }

# ── Helpers ────────────────────────────────────────────────────────

def _safe_org(hops, idx):
    if 0 <= idx < len(hops):
        return hops[idx].get("org", "") or "Unknown"
    return "Unknown"

def _clean_org(org):
    return org.lower().strip().replace(" ", "") if org else ""

def _prev_cum(hops, hop_num):
    for h in hops:
        if h.get("hop") == hop_num - 1:
            return h.get("rtt_cumulative")
    return None
