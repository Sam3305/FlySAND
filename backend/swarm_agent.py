import asyncio
import aiosqlite
import random
import uuid
from datetime import datetime

# Define our target flight for the simulation
TARGET_FLIGHT = '6E-101' # DEL-BOM

class PassengerAgent:
    def __init__(self, persona):
        self.agent_id = f"bot_{str(uuid.uuid4())[:6]}"
        self.persona = persona

    async def evaluate_and_buy(self, db_path):
        """The core logic for each micro-agent."""
        async with aiosqlite.connect(db_path) as db:
            # 1. Agent checks the live price and inventory
            async with db.execute('SELECT available_seats, final_dynamic_price_inr FROM flights WHERE flight_id = ?', (TARGET_FLIGHT,)) as cursor:
                row = await cursor.fetchone()
            
            if not row or row[0] <= 0:
                return False # Flight not found or sold out
            
            available_seats, current_price = row
            will_buy = False

            # 2. The Persona Logic Matrix
            if self.persona == "Budget Student":
                # High price sensitivity [cite: 15]
                if current_price < 5000:
                    will_buy = True
            
            elif self.persona == "Corporate Exec":
                # Zero price sensitivity, pays up to 25k [cite: 17, 18]
                if current_price <= 25000:
                    will_buy = True
            
            elif self.persona == "Festival Traveler":
                # High FOMO: Buys instantly if seats drop below 20 [cite: 20, 21]
                if available_seats < 20:
                    will_buy = True

            # 3. The Execution (Purchasing the ticket)
            if will_buy:
                # We use a strict WHERE clause to prevent Race Conditions!
                cursor = await db.execute('''
                    UPDATE flights 
                    SET available_seats = available_seats - 1 
                    WHERE flight_id = ? AND available_seats > 0
                ''', (TARGET_FLIGHT,))
                
                # If the update was successful, record the booking
                if cursor.rowcount > 0:
                    booking_id = f"bkg_{str(uuid.uuid4())[:8]}"
                    await db.execute('''
                        INSERT INTO bookings (booking_id, flight_id, agent_id, agent_persona, price_paid, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (booking_id, TARGET_FLIGHT, self.agent_id, self.persona, current_price, datetime.now().isoformat()))
                    
                    await db.commit()
                    print(f"🟢 [{self.persona}] booked {TARGET_FLIGHT} for ₹{current_price} | Seats left: {available_seats - 1}")
                    return True
                else:
                    print(f"🔴 [{self.persona}] failed to book. Someone else grabbed the last seat!")
            return False

async def generate_swarm():
    """Spawns hundreds of agents concurrently[cite: 10, 48]."""
    db_path = 'aerosync.db'
    personas = ["Budget Student", "Corporate Exec", "Festival Traveler"]
    
    print("🌪️ WARNING: Releasing the Autobooking Swarm...")
    
    # Create 50 random agents
    tasks = []
    for _ in range(50):
        random_persona = random.choice(personas)
        agent = PassengerAgent(random_persona)
        # Random sleep simulates realistic human click delays
        await asyncio.sleep(random.uniform(0.1, 1.0))
        tasks.append(agent.evaluate_and_buy(db_path))
    
    # Run all 50 agents at the exact same time
    await asyncio.gather(*tasks)
    print("🏁 Swarm attack complete.")

if __name__ == "__main__":
    asyncio.run(generate_swarm())