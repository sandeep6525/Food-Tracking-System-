import math

def travel_days(distance_km: float, avg_kmph: float, drive_hours_per_day: float) -> float:
    if not avg_kmph or not drive_hours_per_day:
        return 0.0
    total_hours = distance_km / max(avg_kmph, 1e-6)
    return total_hours / max(drive_hours_per_day, 1e-6)

def suggest_tomato_type_simple(days: float, temp_c: float, rain_risk: str) -> str:
    if days is None:
        days = 0
    if temp_c is None:
        temp_c = 25

    if days > 5 or (rain_risk == 'high' and days > 3):
        return "Green Tomato"
    if days <= 2 and 15 <= temp_c <= 30 and rain_risk != 'high':
        return "Red Tomato"
    if days <= 3 and temp_c <= 28:
        return "Roma Tomato"
    return "Cherry Tomato"

def tomato_recommendations(distance_km, eta_days, temp_c, rain_risk, road_type):
    notes = []

    if distance_km > 500:
        notes.append("Use ventilated crates and consider refrigerated transport if temp > 30°C.")
    if temp_c >= 30:
        notes.append("High temperature: pack with cool packs; avoid mid-day loading.")
    if rain_risk == 'high':
        notes.append("High rain risk: waterproof covers and avoid rough roads where possible.")
    if road_type in ('poor', 'mixed'):
        notes.append("Rough roads: use shock-absorbing packaging and stack lower.")

    predicted = "firm"
    if eta_days >= 5 or temp_c > 30:
        predicted = "overripe risk"
    elif eta_days <= 2 and rain_risk != 'high':
        predicted = "good"

    return notes, predicted
