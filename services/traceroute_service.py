import asyncio
import re

LINE_RE = re.compile(
    r'^\s*(?P<hop>\d+)\s+'
    r'(?:(?P<ip>\d+\.\d+\.\d+\.\d+)|(?P<timeout>\*))\s+'
    r'(?P<as>\[AS\d+\]|\[\*{1,2}\])?\s*'
    r'(?:(?P<rtt>[\d.]+)\s*ms)?'
    r'.*'
    r'(?P<mpls>MPLS:L=\d+)?'
    r'\s*(?P<icmp_err>![HNXP])?'
    r'\s*$'
)

async def run_trace(target_domain, max_hops=30):
    proc = await asyncio.create_subprocess_exec(
        "traceroute", "-n", "-w", "1", "-q", "1", "-A", "-e",
        "-m", str(max_hops), target_domain,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    seen = set()
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="ignore").strip()
        if not text or "traceroute to" in text:
            continue
        m = LINE_RE.match(text)
        if not m:
            continue
        hop_num = int(m.group("hop"))
        if hop_num in seen:
            continue
        seen.add(hop_num)
        if m.group("timeout"):
            yield {
                "hop": hop_num,
                "timeout": True,
                "ip": None,
                "rtt_ms": None,
                "asn": None,
                "mpls_label": None,
                "icmp_error": None,
            }
        else:
            rtt = float(m.group("rtt")) if m.group("rtt") else None
            asn_raw = m.group("as") or ""
            asn = None
            if asn_raw and "AS" in asn_raw:
                try:
                    asn = int(asn_raw.strip("[]").lstrip("AS"))
                except ValueError:
                    pass
            mpls = m.group("mpls") or None
            icmp_err = m.group("icmp_err") or None
            yield {
                "hop": hop_num,
                "ip": m.group("ip"),
                "rtt_ms": rtt,
                "asn": asn,
                "mpls_label": mpls,
                "icmp_error": icmp_err,
                "timeout": False,
            }
    await proc.wait()
