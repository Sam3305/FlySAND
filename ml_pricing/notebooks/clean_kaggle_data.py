import pandas as pd

def clean_pricing_data():
    print("Loading raw Kaggle flight dataset...")
    # Group 1 should replace this with the path to the extracted Kaggle CSV
    df = pd.read_csv('AeroSync_Raw_Data/Clean_Dataset.csv')

    # 1. The Scope Constraint: Economy Only (Simulating IndiGo)
    df = df[df['class'] == 'Economy']

    # 2. The Geographic Constraint: The Metro Square
    metro_cities = ['Delhi', 'Mumbai', 'Chennai', 'Kolkata']
    df = df[
        df['source_city'].isin(metro_cities) & 
        df['destination_city'].isin(metro_cities)
    ]

    # 3. The Data Standardization (Crucial step!)
    # We must translate "Delhi" to "DEL" so the AI's data matches Group 3's backend
    iata_map = {
        'Delhi': 'DEL', 
        'Mumbai': 'BOM', 
        'Chennai': 'MAA', 
        'Kolkata': 'CCU'
    }
    df['origin_iata'] = df['source_city'].map(iata_map)
    df['dest_iata'] = df['destination_city'].map(iata_map)

    # 4. Feature Selection (Dropping the noise)
    # The Random Forest only needs variables that actually affect the price
    final_features = [
        'origin_iata', 
        'dest_iata', 
        'days_left',    # How close to departure
        'duration',     # Flight length in hours
        'price'         # The Target Variable (y)
    ]
    clean_df = df[final_features]

    # 5. Export for the Random Forest
    output_path = '../training_data.csv'
    clean_df.to_csv(output_path, index=False)
    
    print(f"Data cleaned successfully!")
    print(f"Total rows ready for ML Training: {len(clean_df)}")

if __name__ == "__main__":
    clean_pricing_data()