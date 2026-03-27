import requests
import json
import os
from datetime import datetime, timedelta

class OpenMeteoService:
    def __init__(self):
        self.current_dir = os.path.dirname(__file__)
        self.config_dir = os.path.join(self.current_dir, 'config')
        try:
            with open(os.path.join(self.config_dir, 'airport_coordinates.json'), 'r') as f:
                self.airports = json.load(f)
        except FileNotFoundError:
            self.airports = {}

        # ── In-memory cache ───────────────────────────────────────────────────
        # Key: (destination_iata, days_to_flight)
        # Value: atmospheric profile dict
        #
        # WHY THIS MATTERS:
        # The seeder builds 1,080 documents: 12 routes × 3 slots × 30 days.
        # Weather is keyed on (destination, days_to_flight) — only 4 destinations
        # × 30 days = 120 unique combinations. Every combination is requested
        # 3× (once per slot, same destination, same day) → 900 duplicate API calls.
        # This cache collapses 1,080 calls to 120, cutting seeder time by ~88%.
        self._weather_cache: dict = {}

        # Failsafe standard ISA atmosphere matching your new schema
        self.default_profile = {
            "surface_thermodynamics": {"temp_c": 15.0, "pressure_hpa": 1013.25, "humidity_percent": 60.0},
            "cruise_atmosphere": {"jet_stream_headwind_kph": 50.0, "temp_250hPa_c": -40.0},
            "chaos_factors": {"cape_instability": 200.0, "precipitation_mm": 0.0, "icing_risk_critical": False}
        }

    def _build_atmospheric_profile(self, surface_temp: float, surface_wind: float, precip: float) -> dict:
        """
        Takes real surface data and builds a full vertical aviation profile.
        Simulates upper air conditions to save API bandwidth.
        """
        # 1. Thermodynamics
        # Standard sea level pressure is 1013.25. High temps usually mean slightly lower pressure.
        simulated_pressure = 1013.25 - ((surface_temp - 15) * 0.5)
        
        # 2. Cruise Atmosphere (34,000 ft / 250hPa)
        # Cruise temp is usually surface temp minus ~2 degrees per 1000ft (ISA lapse rate)
        cruise_temp = surface_temp - (34.0 * 2.0)
        # Simulate jet stream speed based on surface turbulence
        jet_stream = 60.0 + (surface_wind * 2.5) 

        # 3. Chaos Factors
        # CAPE (Convective Available Potential Energy) spikes in hot, wet conditions (thunderstorms)
        cape = 1500.0 if (surface_temp > 30 and precip > 5.0) else (300.0 + precip * 20)
        
        # Icing is critical if there is visible moisture (precip) AND surface temps are near freezing
        icing_risk = bool(precip > 1.0 and -5.0 <= surface_temp <= 5.0)

        return {
            "surface_thermodynamics": {
                "temp_c": round(surface_temp, 1),
                "pressure_hpa": round(simulated_pressure, 1),
                "humidity_percent": 75.0 if precip > 0 else 45.0
            },
            "cruise_atmosphere": {
                "jet_stream_headwind_kph": round(jet_stream, 1),
                "temp_250hPa_c": round(cruise_temp, 1)
            },
            "chaos_factors": {
                "cape_instability": round(cape, 1),
                "precipitation_mm": round(precip, 1),
                "icing_risk_critical": icing_risk
            }
        }

    def get_route_weather_profile(self, destination_iata: str, days_to_flight: int) -> dict:
        """Fetches surface metrics and generates a full flight weather profile.

        Results are cached by (destination, days_to_flight) so that the seeder
        only makes one real HTTP call per unique combination instead of 9×
        (one per departure slot × routes sharing the same destination).
        """
        cache_key = (destination_iata, days_to_flight)
        if cache_key in self._weather_cache:
            return self._weather_cache[cache_key]

        if destination_iata not in self.airports:
            return self.default_profile

        lat = self.airports[destination_iata]['lat']
        lon = self.airports[destination_iata]['lon']

        metrics = "wind_speed_10m_max,temperature_2m_max,precipitation_sum"

        try:
            if days_to_flight <= 14:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily={metrics}&timezone=auto&forecast_days=16"
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                data = response.json()

                profile = self._build_atmospheric_profile(
                    surface_temp=data['daily']['temperature_2m_max'][days_to_flight],
                    surface_wind=data['daily']['wind_speed_10m_max'][days_to_flight],
                    precip=data['daily']['precipitation_sum'][days_to_flight]
                )
            else:
                target_date = datetime.now() + timedelta(days=days_to_flight)
                last_year_date = (target_date - timedelta(days=365)).strftime('%Y-%m-%d')
                url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={last_year_date}&end_date={last_year_date}&daily={metrics}&timezone=auto"

                response = requests.get(url, timeout=5)
                response.raise_for_status()
                data = response.json()

                profile = self._build_atmospheric_profile(
                    surface_temp=data['daily']['temperature_2m_max'][0],
                    surface_wind=data['daily']['wind_speed_10m_max'][0],
                    precip=data['daily']['precipitation_sum'][0]
                )

            self._weather_cache[cache_key] = profile
            return profile

        except Exception as e:
            print(f"⚠️ Weather API warning: {e}. Defaulting to standard ISA atmosphere.")
            self._weather_cache[cache_key] = self.default_profile
            return self.default_profile

if __name__ == "__main__":
    # Test the module directly
    weather = OpenMeteoService()
    profile = weather.get_route_weather_profile("BOM", days_to_flight=1)
    print(json.dumps(profile, indent=4))