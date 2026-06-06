import math

FIBER_SPEED = 199792.0

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def fiber_latency(distance_km):
    return (distance_km / FIBER_SPEED) * 1000

def compound_rtt(prev_lat, prev_lng, cur_lat, cur_lng, actual_rtt_ms):
    if None in (prev_lat, prev_lng, cur_lat, cur_lng, actual_rtt_ms):
        return actual_rtt_ms or 0
    dist = haversine(prev_lat, prev_lng, cur_lat, cur_lng)
    min_rtt = fiber_latency(dist) * 2
    return max(actual_rtt_ms, min_rtt)

def interpolate_path(coords, segment_km=400):
    if len(coords) < 2:
        return coords
    result = [coords[0]]
    for i in range(len(coords) - 1):
        lat1, lng1 = coords[i]
        lat2, lng2 = coords[i + 1]
        dist = haversine(lat1, lng1, lat2, lng2)
        steps = max(1, int(dist / segment_km))
        for j in range(1, steps + 1):
            frac = j / (steps + 1)
            lat = lat1 + (lat2 - lat1) * frac
            lng = lng1 + (lng2 - lng1) * frac
            result.append((lat, lng))
        result.append(coords[i + 1])
    return result
