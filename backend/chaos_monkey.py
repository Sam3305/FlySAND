import asyncio
import aiosqlite
import random
import sys

async def unleash_chaos():
    db_path = 'aerosync.db' 
    print("🌪️ Chaos Monkey is online. Watching the skies...")

    while True:
        # 1. Wait a random amount of time (simulated hours/minutes)
        await asyncio.sleep(random.uniform(3.0, 8.0))

        # 2. Roll the weighted digital dice (1 to 100) [cite: 27]
        dice_roll = random.randint(1, 100)

        async with aiosqlite.connect(db_path) as db:
            # We only care if the roll is 20 or under
            if dice_roll <= 20: 
                
                # Fetch flights that are still operating normally
                async with db.execute("SELECT flight_id, route FROM flights WHERE status = 'Scheduled'") as cursor:
                    active_flights = await cursor.fetchall()

                if not active_flights:
                    print("🌤️ Skies are clear. No active flights to disrupt.")
                    await asyncio.sleep(5)
                    continue

                # Pick a random flight to attack
                target_flight = random.choice(active_flights)
                flight_id, route = target_flight

                # -- THE DISRUPTION MATRIX --
                
                # Critical Grounding: 5% chance in our rapid simulation [cite: 31]
                if dice_roll <= 5: 
                    await db.execute("UPDATE flights SET status = 'CANCELLED' WHERE flight_id = ?", (flight_id,))
                    await db.commit()
                    print(f"🚨 CRITICAL (Roll {dice_roll}): Aircraft On Ground (AOG) failure!")
                    print(f"❌ Flight {flight_id} ({route}) has been CANCELLED. Passengers are stranded.")
                
                # Minor Disruption: 15% chance [cite: 28]
                else: 
                    print(f"🌩️ MINOR (Roll {dice_roll}): ATC Delay / Weather cell on route {route}.")
                    print(f"⚠️ Flight {flight_id} will burn extra fuel. Logging penalty...")

if __name__ == "__main__":
    # This prevents a common Windows asyncio error when stopping the script
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(unleash_chaos())
    except KeyboardInterrupt:
        print("\n🛑 Chaos Monkey shut down.")