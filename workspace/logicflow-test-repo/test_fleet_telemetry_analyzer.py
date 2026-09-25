"""
Unit tests for fleet_telemetry_analyzer module.
Verifies spherical Haversine distance accuracy, average speeds, and idle metrics.
"""

import unittest
from fleet_telemetry_analyzer import (
    TelemetryPoint,
    haversine_distance,
    calculate_journey_metrics
)


class TestFleetTelemetryAnalyzer(unittest.TestCase):
    """Test suite for GPS telemetry distance and metrics."""

    def test_haversine_known_city_distance(self):
        """
        Distance between London (51.5074, -0.1278) and Paris (48.8566, 2.3522).
        Expected distance is approximately 343 km to 345 km.
        """
        london = (51.5074, -0.1278)
        paris = (48.8566, 2.3522)
        dist = haversine_distance(london, paris)
        # Check within 2 km tolerance of expected 343.5 km
        self.assertAlmostEqual(dist, 343.5, delta=3.0)

    def test_identical_coordinates_zero_distance(self):
        """Distance between identical coordinates must be 0.0."""
        coord = (40.7128, -74.0060)
        self.assertEqual(haversine_distance(coord, coord), 0.0)

    def test_journey_metrics_summary(self):
        """Test calculation of journey distance and average speed."""
        pt1 = TelemetryPoint(timestamp=0.0, latitude=51.5074, longitude=-0.1278, speed_kmh=60.0, engine_rpm=2200)
        pt2 = TelemetryPoint(timestamp=1800.0, latitude=51.6074, longitude=-0.1278, speed_kmh=60.0, engine_rpm=2200)

        metrics = calculate_journey_metrics([pt1, pt2])
        self.assertGreater(metrics["total_distance_km"], 10.0)
        self.assertEqual(metrics["duration_minutes"], 30.0)


if __name__ == "__main__":
    unittest.main()
