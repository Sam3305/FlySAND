from openap import prop
import json

class AircraftDataService:
    def __init__(self):
        self.fleet_map = {
            "A320neo": "A20N",
            "A321neo": "A21N",
            "A320ceo": "A320",
            "ATR72": "AT72"
        }
        
        # OpenAP doesn't always track passengers, so we use IndiGo's exact seat counts!
        self.indigo_pax = {
            "A20N": 186,
            "A21N": 222,
            "A320": 180,
            "AT72": 78
        }

    def get_aircraft_specs(self, model_name: str) -> dict:
        icao_code = self.fleet_map.get(model_name)
        if not icao_code:
            raise ValueError(f"Aircraft {model_name} not found.")

        print(f"Querying OpenAP database for {icao_code}...")
        
        try:
            # 1. Fetch the raw dictionary from OpenAP
            aircraft_data = prop.aircraft(icao_code)
            
            # 2. Safely extract nested data (handles different OpenAP library versions)
            limits = aircraft_data.get('limits', {})
            cruise = aircraft_data.get('cruise', {})
            aero = aircraft_data.get('aero', {})
            
            # 3. Build the exact payload for the Physics Engine using .get() fallbacks
            specs = {
                "model": model_name,
                "icao_code": icao_code,
                "max_passengers": aircraft_data.get('pax', limits.get('pax', self.indigo_pax.get(icao_code))),
                "operating_empty_weight_kg": aircraft_data.get('oew', limits.get('oew')),
                "max_takeoff_weight_kg": aircraft_data.get('mtow', limits.get('mtow')),
                "cruise_mach": cruise.get('mach', 0.78),
                "wing_area_m2": aero.get('S', 122.6) 
            }
            return specs
            
        except Exception as e:
            print(f"CRITICAL: Failed to parse OpenAP data. {e}")
            # If it fails, print exactly what OpenAP *did* return so you can debug
            print("Available keys were:", aircraft_data.keys() if 'aircraft_data' in locals() else "None")
            return None