import math

class ThermodynamicCalculator:
    def __init__(self):
        # Universal Gas Constants (J / kg·K)
        self.R_d = 287.05
        self.R_v = 461.495
        self.rho_isa = 1.225 # Standard sea-level density (kg/m^3)
        self.v_tas_cruise = 830.0 # True Airspeed in km/h

    def calculate_environmental_impact(self, distance_km: float, weather_payload: dict) -> dict:
        """Translates meteorological data into aerodynamic fuel penalties and times."""
        
        surface = weather_payload['surface_thermodynamics']
        cruise = weather_payload['cruise_atmosphere']
        chaos = weather_payload['chaos_factors']
        
        # --- 1. THERMODYNAMIC DENSITY MATH (Surface) ---
        tc = surface['temp_c']
        tk = tc + 273.15
        p_total_hpa = surface['pressure_hpa']
        rh = surface['humidity_percent']
        
        # Tetens Equation for Vapor Pressure
        e_s = 6.1078 * (10 ** ((7.5 * tc) / (tc + 237.3)))
        p_v_hpa = e_s * (rh / 100.0)
        p_d_hpa = p_total_hpa - p_v_hpa
        
        # Convert hPa to Pascals for the density equation (* 100)
        rho_actual = ((p_d_hpa * 100) / (self.R_d * tk)) + ((p_v_hpa * 100) / (self.R_v * tk))
        
        # Calculate Thrust Lapse Penalty (Density Ratio)
        # If rho is lower than ISA (1.225), the engine works harder.
        density_ratio = rho_actual / self.rho_isa
        # If density is 90% of ISA, penalty multiplier is roughly 1.10 (10% more fuel to climb)
        density_burn_multiplier = 1.0 + (1.0 - density_ratio) if density_ratio < 1.0 else 1.0


        # --- 2. KINEMATIC WIND MATH (Cruise) ---
        # Apply the Jet Stream vector to the True Airspeed
        jet_headwind = cruise['jet_stream_headwind_kph']
        v_ground = self.v_tas_cruise - jet_headwind
        
        # Safety net: Ground speed cannot be zero or negative
        v_ground = max(v_ground, 400.0) 
        
        actual_flight_time_hrs = distance_km / v_ground


        # --- 3. AERODYNAMIC CHAOS MULTIPLIERS ---
        chaos_multiplier = 1.0
        holding_time_mins = 0
        
        # Icing severely destroys Lift-to-Drag ratio (L/D) and bleeds engine thrust
        if chaos['icing_risk_critical']:
            chaos_multiplier += 0.12 # +12% fuel burn penalty
            holding_time_mins += 15  # 15 mins ATC holding due to weather delays
            
        # Severe atmospheric instability (Turbulence) increases effective drag
        if chaos['cape_instability'] > 1000:
            chaos_multiplier += 0.05 # +5% fuel burn penalty
            holding_time_mins += 10
            
        # Heavy Precipitation causes runway friction and visibility delays
        if chaos['precipitation_mm'] > 5.0:
            holding_time_mins += 15

        # --- 4. THE FINAL MULTIPLIER ---
        # Combine the thermodynamic climb penalty with the cruise drag penalties
        total_burn_multiplier = density_burn_multiplier * chaos_multiplier

        return {
            "calculated_rho_kg_m3": round(rho_actual, 3),
            "density_ratio": round(density_ratio, 3),
            "v_ground_kph": round(v_ground, 1),
            "actual_flight_time_hrs": round(actual_flight_time_hrs, 3),
            "total_burn_multiplier": round(total_burn_multiplier, 3),
            "atc_holding_time_mins": holding_time_mins
        }

# --- Quick Test Block ---
if __name__ == "__main__":
    calc = ThermodynamicCalculator()
    
    # Mock payload from the fetcher
    mock_weather = {
        "surface_thermodynamics": {"temp_c": 35.0, "pressure_hpa": 1005.0, "humidity_percent": 85.0},
        "cruise_atmosphere": {"jet_stream_headwind_kph": 80.0, "temp_250hPa_c": -40.0},
        "chaos_factors": {"cape_instability": 1200.0, "precipitation_mm": 12.0, "icing_risk_critical": False}
    }
    
    results = calc.calculate_environmental_impact(1140.0, mock_weather)
    import json
    print(json.dumps(results, indent=4))