import math
from datetime import datetime, timedelta
import requests
import os

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def plan_eta(start_dt, days):
    if not start_dt or not days:
        return None
    return start_dt + timedelta(days=float(days))

def osrm_route(lat1, lon1, lat2, lon2):
    """Return (distance_km, duration_hours) using OSRM public server. Fallback: None."""
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false&alternatives=false"
        r = requests.get(url, timeout=8)
        j = r.json()
        if j.get('code') == 'Ok' and j.get('routes'):
            dist_m = j['routes'][0]['distance']
            dur_s = j['routes'][0]['duration']
            return dist_m/1000.0, dur_s/3600.0
    except Exception:
        pass
    return None
