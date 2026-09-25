"""
Fleet GPS Telemetry & Journey Analytics Module
Computes route distances via Haversine spherical formula,
average speeds, fuel consumption models, and speeding alert windows.
"""

import math
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass


EARTH_RADIUS_KM = 6371.0
SPEEDING_THRESHOLD_KMH = 100.0
IDLE_FUEL_RATE_LITER_PER_HR = 1.80  # Liters burned per hour while idling


@dataclass
class TelemetryPoint:
    """Represents a GPS timestamped waypoint."""
    timestamp: float  # Epoch seconds
    latitude: float   # Decimal degrees
    longitude: float  # Decimal degrees
    speed_kmh: float   # Instantaneous speed
    engine_rpm: int    # Engine RPM


def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    Calculate great-circle distance between two GPS coordinates in kilometers.
    Coordinates format: (latitude, longitude) in degrees.
    """
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    # BUG: Mathematical logic error:
    # Passed raw degrees into math.sin/cos instead of converting to radians!
    # Correct formula:
    # phi1, phi2 = math.radians(lat1), math.radians(lat2)
    # delta_phi = math.radians(lat2 - lat1)
    # delta_lambda = math.radians(lon2 - lon1)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (math.sin(delta_lat / 2.0) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2)
    
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(EARTH_RADIUS_KM * c, 2)


def calculate_journey_metrics(waypoints: List[TelemetryPoint]) -> Dict[str, Any]:
    """
    Analyze sequence of telemetry points to compute total distance,
    average speed, idle duration, and speeding incidents.
    """
    if len(waypoints) < 2:
        return {
            "total_distance_km": 0.0,
            "duration_minutes": 0.0,
            "average_speed_kmh": 0.0,
            "idle_minutes": 0.0,
            "speeding_incidents": 0
        }

    total_dist = 0.0
    idle_seconds = 0.0
    speeding_count = 0

    for i in range(len(waypoints) - 1):
        pt1 = waypoints[i]
        pt2 = waypoints[i + 1]

        leg_dist = haversine_distance((pt1.latitude, pt1.longitude), (pt2.latitude, pt2.longitude))
        total_dist += leg_dist

        time_delta = pt2.timestamp - pt1.timestamp
        if pt1.speed_kmh < 2.0 and pt1.engine_rpm > 500:
            idle_seconds += time_delta

        if pt1.speed_kmh > SPEEDING_THRESHOLD_KMH:
            speeding_count += 1

    total_duration_hrs = (waypoints[-1].timestamp - waypoints[0].timestamp) / 3600.0
    avg_speed = round(total_dist / total_duration_hrs, 2) if total_duration_hrs > 0 else 0.0

    return {
        "total_distance_km": round(total_dist, 2),
        "duration_minutes": round(total_duration_hrs * 60.0, 2),
        "average_speed_kmh": avg_speed,
        "idle_minutes": round(idle_seconds / 60.0, 2),
        "speeding_incidents": speeding_count
    }
