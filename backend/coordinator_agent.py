import asyncio
import aiosqlite
import sys

async def run_coordinator():
    db_path = 'aerosync.db'
    print("🦸‍♂️ Disruption Coordinator is online. Monitoring for Cancellations...")

    while True:
        await asyncio.sleep(2) # Check the database every 2 seconds

        async with aiosqlite.connect(db_path) as db:
            # 1. Find any flights that were just CANCELLED
            async with db.execute("SELECT flight_id, route FROM flights WHERE status = 'CANCELLED'") as cursor:
                cancelled_flights = await cursor.fetchall()

            for flight in cancelled_flights:
                cancelled_flight_id, route = flight
                print(f"\n🚨 ALERT: Detected cancellation for {cancelled_flight_id} ({route}). Initiating recovery...")

                # 2. Ingest the Passenger Manifest (Find stranded passengers)
                async with db.execute("SELECT booking_id, agent_id FROM bookings WHERE flight_id = ? AND status = 'CONFIRMED'", (cancelled_flight_id,)) as cursor:
                    stranded_passengers = await cursor.fetchall()
                
                if not stranded_passengers:
                    print("ℹ️ No passengers were booked on this flight. Moving on.")
                else:
                    stranded_count = len(stranded_passengers)
                    print(f"👥 Found {stranded_count} stranded passengers. Searching for alternatives...")

                    # 3. Search for alternative flights on the same route
                    async with db.execute("SELECT flight_id, available_seats FROM flights WHERE route = ? AND status = 'Scheduled' AND available_seats > 0 ORDER BY departure_time ASC", (route,)) as cursor:
                        alt_flights = await cursor.fetchall()

                    passengers_reallocated = 0

                    # 4. Reallocate passengers to new flights
                    for alt_flight in alt_flights:
                        alt_flight_id, available_seats = alt_flight
                        
                        while available_seats > 0 and stranded_passengers:
                            passenger = stranded_passengers.pop(0)
                            booking_id = passenger[0]

                            # Move passenger to the new flight
                            await db.execute("UPDATE bookings SET flight_id = ?, status = 'REALLOCATED' WHERE booking_id = ?", (alt_flight_id, booking_id))
                            
                            # Remove a seat from the alternative flight
                            await db.execute("UPDATE flights SET available_seats = available_seats - 1 WHERE flight_id = ?", (alt_flight_id,))
                            
                            available_seats -= 1
                            passengers_reallocated += 1
                            
                    # 5. The Financial Hit
                    compensation_penalty = stranded_count * 1500
                    print(f"✅ Reallocated {passengers_reallocated} passengers to alternative flights.")
                    if stranded_passengers:
                        print(f"❌ Could not reallocate {len(stranded_passengers)} passengers (No capacity).")
                    print(f"💸 FINANCIAL HIT: Logged ₹{compensation_penalty} in passenger compensation penalties.")

                # 6. Mark the flight as resolved so we don't process it again
                await db.execute("UPDATE flights SET status = 'CANCELLED_RESOLVED' WHERE flight_id = ?", (cancelled_flight_id,))
                await db.commit()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(run_coordinator())
    except KeyboardInterrupt:
        print("\n🛑 Coordinator shut down.")