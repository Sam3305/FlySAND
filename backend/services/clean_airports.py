import pandas as pd
import json
import os

def clean_airport_data():
    # 1. Define your Metro Square scope
    target_airports = ['DEL', 'BOM', 'MAA', 'CCU']
    
    print("Loading raw global airports database...")
    # Assuming the raw CSV is stored in a folder outside the repo or ignored by git
    # Replace the path with wherever Group 3 saved the OurAirports CSV
    raw_df = pd.read_csv('AeroSync_Raw_Data/airports.csv')
    
    # 2. Filter for only Indian airports
    india_df = raw_df[raw_df['iso_country'] == 'IN']
    
    # 3. Filter down to just the Metro Square
    metro_df = india_df[india_df['iata_code'].isin(target_airports)]
    
    # 4. Keep ONLY the columns the Physics Engine needs for distance math
    clean_df = metro_df[['iata_code', 'name', 'latitude_deg', 'longitude_deg']]
    
    # 5. Convert it to a dictionary so it's easy to save as JSON
    # Orient='records' makes it a clean list of objects
    airport_dict = clean_df.to_dict(orient='records')
    
    # Restructure it so the IATA code is the key for instant O(1) lookups
    final_json = {
        item['iata_code']: {
            "name": item['name'],
            "lat": item['latitude_deg'],
            "lon": item['longitude_deg']
        } for item in airport_dict
    }

    # 6. Save the clean data to your backend config folder
    output_path = 'airport_coordinates.json'
    with open(output_path, 'w') as f:
        json.dump(final_json, f, indent=4)
        
    print(f"Successfully cleaned data! Saved {len(final_json)} airports to {output_path}")

if __name__ == "__main__":
    clean_airport_data()