import json
import os
from .physics_engine import AeroPhysicsEngine
from .event_oracle import EventOracle

class AirlineEconomicsEngine:
    def __init__(self):
        self.current_dir = os.path.dirname(__file__)
        self.config_dir = os.path.join(self.current_dir, 'config')
        
        self.fuel_data = self._load_json('atf_prices.json')
        self.physics = AeroPhysicsEngine()
        self.oracle = EventOracle()

        # --- LCC FINANCIAL CONSTANTS (Based on A320neo Indian Operations) ---
        # Assuming ~13.5 hours of daily utilization to apportion fixed costs
        
        self.crew_cost_per_bh = 18000.0      # Salaries, layovers, training per block hour
        self.maintenance_per_bh = 85000.0    # PBH contracts, line checks per block hour
        self.lease_cost_per_bh = 75000.0     # Apportioned monthly lease (₹2.5-3.5Cr) per block hour
        self.insurance_cost_per_bh = 4000.0  # Apportioned Hull & Liability insurance per hour
        
        self.ground_handling_per_turn = 15000.0 # Pushback, baggage, cleaning per cycle
        self.atc_nav_base_fee = 12000.0         # Route navigation charges
        self.landing_fee_per_ton = 600.0        # Metro airport landing weight charges

        # IOC Markup (Sales, Admin, Marketing) as a % of DOC
        self.ioc_markup_pct = 0.12 

        self.fixed_taxes_and_fees = 1500

        #base profit margin
        self.base_profit_margin=13.5

    def _load_json(self, filename):
        with open(os.path.join(self.config_dir, filename), 'r') as f:
            return json.load(f)

    def calculate_trip_economics(self, origin: str, destination: str, model_name: str, extra_payload_kg: float = 0.0) -> dict:
        print(f"\n📊 EXECUTING LCC FINANCIAL DISPATCH: {origin} ✈️ {destination}")
        
        # 1. Fetch Physical Flight Data
        flight = self.physics.calculate_physical_flight(origin, destination, model_name, extra_payload_kg)
        
        block_hrs = flight['block_time_hrs']
        pax_capacity = flight['pax_capacity']
        fuel_kg = flight['total_fuel_burn_kg']
        distance_km = flight['distance_km']
        
        # We need MTOW for landing fees (fetch from aircraft service)
        specs = self.physics.aircraft_service.get_aircraft_specs(model_name)
        mtow_tons = specs.get('max_takeoff_weight_kg', 79000) / 1000.0

        # --- 2. DIRECT OPERATING COSTS (DOC) ---
        
        # A. Fuel Cost
        prices = self.fuel_data.get('prices_inr_per_kl', {})
        atf_price = prices.get(origin, 90000.0)
        fuel_cost_inr = (fuel_kg / 800.0) * atf_price

        # B. Block Hour Driven Costs
        crew_cost = self.crew_cost_per_bh * block_hrs
        maintenance_cost = self.maintenance_per_bh * block_hrs
        lease_cost = self.lease_cost_per_bh * block_hrs
        insurance_cost = self.insurance_cost_per_bh * block_hrs

        # C. Cycle/Sector Driven Costs
        landing_fee = mtow_tons * self.landing_fee_per_ton
        airport_atc_cost = landing_fee + self.atc_nav_base_fee
        ground_handling = self.ground_handling_per_turn

        total_doc = fuel_cost_inr + crew_cost + maintenance_cost + lease_cost + insurance_cost + airport_atc_cost + ground_handling

        # --- 3. INDIRECT OPERATING COSTS (IOC) ---
        # Covers distribution, HQ overheads, and marketing
        total_ioc = total_doc * self.ioc_markup_pct

        # --- 4. TOTAL ECONOMICS & CASK MATH ---
        total_trip_cost = total_doc + total_ioc
        
        # Available Seat Kilometers (ASK)
        ask = pax_capacity * distance_km
        
        cask = total_trip_cost / ask if ask > 0 else 0
        break_even_base_fare = total_trip_cost / pax_capacity
        return {
            "flight_details": {
                "route": flight['route'],
                "distance_km": distance_km,
                "block_time_hrs": round(block_hrs, 2),
                "ask": round(ask, 2)
            },
            "direct_operating_costs": {
                "fuel_inr": round(fuel_cost_inr, 2),
                "crew_inr": round(crew_cost, 2),
                "maintenance_inr": round(maintenance_cost, 2),
                "ownership_lease_inr": round(lease_cost, 2),
                "airport_atc_inr": round(airport_atc_cost, 2),
                "ground_handling_inr": round(ground_handling, 2),
                "total_doc_inr": round(total_doc, 2)
            },
            "indirect_operating_costs": {
                "total_ioc_inr": round(total_ioc, 2)
            },
            "kpi_metrics": {
                "total_trip_cost_inr": round(total_trip_cost, 2),
                "cask_inr": round(cask, 2),
                "break_even_base_fare_inr": round(break_even_base_fare, 2)
            }
        }       

   # Replaces calculate_dynamic_price
    def generate_market_fares(self, origin: str, destination: str, model_name: str, flight_date: str) -> dict:
        """
        Takes the highly accurate per-passenger break-even cost and applies 
        market demand from the Event Oracle to generate realistic ticket prices.
        """
        # 1. Let the engine do the heavy lifting to find the exact per-seat cost
        economics = self.calculate_trip_economics(origin, destination, model_name)
        break_even_fare = economics['kpi_metrics']['break_even_base_fare_inr']

        # Add pure taxes on top of the break-even cost (e.g., UDF, PSF)
        fare_with_taxes = break_even_fare + self.fixed_taxes_and_fees

        # 2. Calculate the standard ticket price (Cost + Standard LCC Profit Margin)
        standard_ticket_price = fare_with_taxes * (1.0 + self.base_profit_margin)

        # 3. Fetch Market Demand Signals
        route_string = f"{origin}-{destination}"
        market_data = self.oracle.get_market_signals(flight_date, route_string)
        demand_multiplier = market_data.get("net_demand_multiplier", 1.0)
        active_events = market_data.get("active_events", [])

        # 4. Generate Final Dynamic Price
        # LCCs rarely apply massive multipliers to the government tax portion, 
        # so we apply the multiplier mostly to the base fare.
        dynamic_base_fare = (standard_ticket_price - self.fixed_taxes_and_fees) * demand_multiplier
        final_dynamic_price = dynamic_base_fare + self.fixed_taxes_and_fees

        return {
            "route": route_string,
            "flight_date": flight_date,
            "pricing_breakdown": {
                "per_seat_break_even_inr": round(break_even_fare, 2),
                "standard_ticket_price_inr": round(standard_ticket_price, 2),
                "demand_multiplier": demand_multiplier,
                "final_dynamic_price_inr": round(final_dynamic_price, 2)
            },
            "market_context": {
                "active_events": active_events
            }
        }

# --- Accurate LCC Test Block ---
if __name__ == "__main__":
    engine = AirlineEconomicsEngine()
    
    # Simulating a flight from Delhi to Kolkata right before Durga Puja
    # Note: We now just pass the origin, destination, aircraft, and date.
    # The engine figures out the fuel burn and passenger math automatically!
    result = engine.generate_market_fares(
        origin="DEL", 
        destination="CCU",
        model_name="A320neo",
        flight_date="2026-10-16" 
    )
    
    import json
    print(json.dumps(result, indent=2))
