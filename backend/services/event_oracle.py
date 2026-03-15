import json
import math
import os
from datetime import datetime

class EventOracle:
    def __init__(self, config_filename="events_master.json"):
        """
        Initializes the Event Oracle by loading the master calendar JSON.
        Automatically resolves the path to the 'config' directory.
        """
        # Resolves to backend/services/config/events_master.json
        base_dir = os.path.dirname(__file__)
        config_path = os.path.join(base_dir, 'config', config_filename)
        
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                self.events_data = data.get('events_master', [])
        except FileNotFoundError:
            print(f"Warning: Could not find config file at {config_path}")
            self.events_data = []

    def get_market_signals(self, target_date_str: str, route: str) -> dict:
        """
        Queries the Oracle for a specific date and route.
        Returns a compounded demand multiplier if multiple events overlap.
        """
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        final_multiplier = 1.0
        active_events = []

        for event in self.events_data:
            multiplier = 1.0
            
            if event['demand_curve_type'] == 'spike':
                multiplier = self._calculate_spike(event, target_date, route)
            elif event['demand_curve_type'] == 'plateau':
                multiplier = self._calculate_plateau(event, target_date, route)

            if multiplier > 1.0:
                active_events.append({
                    "event_id": event['event_id'],
                    "route_multiplier": round(multiplier, 3)
                })
                # Compound the multipliers if multiple events happen on the same day
                final_multiplier *= multiplier 

        # Hard cap to prevent runaway pricing if 3 massive events perfectly align
        MAX_MULTIPLIER_CAP = 3.5
        final_multiplier = min(final_multiplier, MAX_MULTIPLIER_CAP)

        return {
            "query_date": target_date_str,
            "route": route,
            "net_demand_multiplier": round(final_multiplier, 3),
            "active_events": active_events
        }

    def _get_route_data(self, event: dict, target_route: str) -> dict:
        """Extracts specific route impacts if they exist in the event payload."""
        for r in event.get('route_impacts', []):
            if r['route'] == target_route:
                return r
        return None

    def _calculate_spike(self, event: dict, target_date: datetime.date, route: str) -> float:
        """Calculates the bell-curve decay for spike events like Diwali."""
        peak_date = datetime.strptime(event['peak_date'], "%Y-%m-%d").date()
        days_diff = (target_date - peak_date).days # Negative = pre-peak, Positive = post-peak

        pre_window = event['pre_event_days']
        post_window = event['post_event_days']

        # If the date is completely outside the impact window, no multiplier applies
        if days_diff < -pre_window or days_diff > post_window:
            return 1.0 

        route_data = self._get_route_data(event, route)
        
        # Determine the maximum multiplier depending on the direction of travel
        if days_diff <= 0:
            max_mult = route_data['pre_peak_multiplier'] if route_data else event['default_network_multiplier']
            window_size = pre_window
        else:
            max_mult = route_data['post_peak_multiplier'] if route_data else event['default_network_multiplier']
            window_size = post_window

        if max_mult <= 1.0:
            return 1.0

        # Math: Bell Curve Decay Formula
        # If the target date is exactly the peak day, return the max multiplier.
        if days_diff == 0 or window_size == 0:
            return max_mult

        # Calculate Sigma so the premium drops to ~10% of its max value at the edge of the window
        sigma_sq = -(window_size ** 2) / (2 * math.log(0.1))
        premium = max_mult - 1.0
        decay_factor = math.exp(- (days_diff ** 2) / (2 * sigma_sq))
        
        return 1.0 + (premium * decay_factor)

    def _calculate_plateau(self, event: dict, target_date: datetime.date, route: str) -> float:
        """Applies a flat multiplier for sustained seasons like Summer Vacation."""
        start_date = datetime.strptime(event['start_date'], "%Y-%m-%d").date()
        end_date = datetime.strptime(event['end_date'], "%Y-%m-%d").date()

        if start_date <= target_date <= end_date:
            route_data = self._get_route_data(event, route)
            if route_data:
                return route_data.get('sustained_multiplier', 1.0)
            return event.get('default_network_multiplier', 1.0)
        
        return 1.0

# Quick debug test - this only runs if you execute the file directly
if __name__ == "__main__":
    oracle = EventOracle()
    # Testing DEL to CCU exactly two days before Durga Puja
    print(json.dumps(oracle.get_market_signals("2026-10-16", "DEL-CCU"), indent=2))