import requests
from bs4 import BeautifulSoup
import json
import os

def scrape_latest_fuel_prices():
    print("Initiating live scrape of IOCL Aviation Fuel database...")
    url = "https://iocl.com/atf-domestic-airlines"
    
    # 1. UPGRADED BROWSER SPOOFING
    # We are giving the script a full Chrome browser fingerprint
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "3"
    }

    current_dir = os.path.dirname(__file__)
    config_dir = os.path.join(current_dir, 'config')
    
    os.makedirs(config_dir, exist_ok=True)
    file_path = os.path.join(config_dir, 'atf_prices.json')
    
    try:
        # Timeout added so the backend doesn't hang forever if the site is slow
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        table = soup.find('table')
        if not table:
            #JS rendering or WAF blocking
            raise ValueError("Table not found in HTML. The site blocked the bot or requires JavaScript rendering.")
            
        rows = table.find_all('tr')
        latest_data = rows[1].find_all('td')
        
        def clean_price(text):
            return float(text.text.replace(',', '').strip())
            
        month_label = latest_data[0].text.strip()
        prices = {
            "DEL": clean_price(latest_data[1]),
            "CCU": clean_price(latest_data[2]),
            "BOM": clean_price(latest_data[3]),
            "MAA": clean_price(latest_data[4])
        }
        
        output_data = {
            "source": "Indian Oil Corporation Limited (IOCL) - Live",
            "effective_date": month_label,
            "prices_inr_per_kl": prices
        }
        print(f"Success! Live data scraped for {month_label}.")

    except Exception as e:
        print(f"SCRAPE FAILED: {e}")
        print("Executing Graceful Fallback to locked MVP baseline data...")
        
        # 2. THE CS FLEX: GRACEFUL DEGRADATION
        # If the government site changes its code, the airline doesn't stop flying.
        output_data = {
            "source": "IOCL (Fallback Baseline)",
            "effective_date": "March 2026 Baseline",
            "prices_inr_per_kl": {
                "DEL": 92323.02,
                "CCU": 95378.02,
                "BOM": 86352.19,
                "MAA": 95770.00
            }
        }
        
    # 3. Always save the JSON, whether from the live scrape or the fallback
    with open(file_path, 'w') as f:
        json.dump(output_data, f, indent=4)
        
    print(f"Data saved to {file_path}")

if __name__ == "__main__":
    scrape_latest_fuel_prices()