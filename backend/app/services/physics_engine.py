import json
import os
from .openap_service import AircraftDataService
from .weather_service import OpenMeteoService
from .physics_engine_math import ThermodynamicCalculator

class AeroPhysicsEngine:
    def __init__(self):
        self.current_dir = os.path.dirname(__file__)
        self.config_dir = os.path.join(self.current_dir, 'config')
        
        self.routes = self._load_json('route_distances.json')
        self.airports = self._load_json('airport_coordinates.json')
        
        self.aircraft_service = AircraftDataService()
        self.weather_service = OpenMeteoService()
        self.thermo_calc = ThermodynamicCalculator()

        self.base_burn_rates = {
            "A20N": 1989, "A21N": 2323, "A320": 2326, "AT72": 800   
        }
        self.verified_pax = {
            "A20N": 186, "A21N": 192, "A320": 153, "AT72": 78
        }

    def _load_json(self, filename):
        try:
            with open(os.path.join(self.config_dir, filename), 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Missing config: {filename}")

    # --- NEW METHOD: Phase Splitter ---
    def _calculate_flight_phases(self, total_distance_km: float, v_ground_kph: float, base_hourly_burn: float) -> dict:
        """Breaks the flight down into LCC standard Climb, Cruise, and Descent profiles."""
        
        # Standard A320 profile assumptions
        climb_dist_km = 130.0
        climb_time_hrs = 0.33  # ~20 mins
        climb_burn_mult = 1.85 # Engines working hard

        descent_dist_km = 160.0
        descent_time_hrs = 0.41 # ~25 mins
        descent_burn_mult = 0.35 # Engines at idle/gliding

        
        cruise_dist_km = total_distance_km - climb_dist_km - descent_dist_km
        cruise_time_hrs = cruise_dist_km / v_ground_kph

        # Calculate isolated fuel burns
        climb_fuel = climb_time_hrs * (base_hourly_burn * climb_burn_mult)
        descent_fuel = descent_time_hrs * (base_hourly_burn * descent_burn_mult)
        base_cruise_fuel = cruise_time_hrs * base_hourly_burn

        return {
            "climb": {"time_hrs": round(climb_time_hrs, 3), "fuel_kg": round(climb_fuel, 2)},
            "cruise": {"time_hrs": round(cruise_time_hrs, 3), "base_fuel_kg": round(base_cruise_fuel, 2)},
            "descent": {"time_hrs": round(descent_time_hrs, 3), "fuel_kg": round(descent_fuel, 2)},
            "active_flight_time_hrs": round(climb_time_hrs + cruise_time_hrs + descent_time_hrs, 3)
        }

    # --- UPDATED MAIN METHOD ---
    def calculate_physical_flight(self, origin: str, destination: str, model_name: str, extra_payload_kg: float = 0.0, days_to_flight: int = 1) -> dict:
        
        route_key = f"{origin}_{destination}"
        distance_km = self.routes[route_key]['distance_km']

        specs = self.aircraft_service.get_aircraft_specs(model_name)
        icao = specs['icao_code']
        actual_pax = self.verified_pax.get(icao, specs['max_passengers'])
        base_hourly_burn = self.base_burn_rates.get(icao, 1989)

        # 1. Fetch Weather & Calculate Thermodynamics
        weather_payload = self.weather_service.get_route_weather_profile(destination, days_to_flight)
        thermo = self.thermo_calc.calculate_environmental_impact(distance_km, weather_payload)

        # 2. Phase-Based Physics Math
        phases = self._calculate_flight_phases(distance_km, thermo['v_ground_kph'], base_hourly_burn)
        
        payload_penalty = extra_payload_kg * 0.03
        
        # We only apply the severe weather/thermodynamic multiplier to the Cruise and Climb phases!
        # Descent is mostly gravity-driven, so it isn't penalized heavily by air density.
        adjusted_climb_fuel = phases['climb']['fuel_kg'] * thermo['total_burn_multiplier']
        adjusted_cruise_fuel = (phases['cruise']['base_fuel_kg'] * thermo['total_burn_multiplier']) + payload_penalty
        descent_fuel = phases['descent']['fuel_kg']
        
        # 3. Ground & ATC Math
        flight_hrs = phases['active_flight_time_hrs']
        ttl_hrs = 0.55 # Taxi, Takeoff, Landing ground time
        holding_hrs = thermo['atc_holding_time_mins'] / 60.0
        
        # Ground engines and holding engines run at low thrust
        ground_and_hold_fuel = (ttl_hrs + holding_hrs) * (base_hourly_burn * 0.40) 
        
        total_fuel_kg = adjusted_climb_fuel + adjusted_cruise_fuel + descent_fuel + ground_and_hold_fuel

        return {
            "route": f"{origin}-{destination}",
            "distance_km": distance_km,
            "aircraft_icao": icao,
            "pax_capacity": actual_pax,
            "flight_phases": {
                "climb_fuel_kg": round(adjusted_climb_fuel, 2),
                "cruise_fuel_kg": round(adjusted_cruise_fuel, 2),
                "descent_fuel_kg": round(descent_fuel, 2),
                "ground_and_hold_fuel_kg": round(ground_and_hold_fuel, 2)
            },
            "block_time_hrs": round(flight_hrs + ttl_hrs + holding_hrs, 3),
            "total_fuel_burn_kg": round(total_fuel_kg, 2),
            "thermodynamic_metrics": thermo 
        }

# --- Quick Test Block ---
if __name__ == "__main__":
    physics = AeroPhysicsEngine()
    results = physics.calculate_physical_flight("DEL", "BOM", "A320neo", days_to_flight=1)
    
    import json
    print(json.dumps(results, indent=4))