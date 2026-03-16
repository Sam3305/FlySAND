import sqlite3
import uuid
from datetime import datetime, timedelta

def initialize_database():
    # Connect to local SQLite file (creates it if it doesn't exist)
    conn = sqlite3.connect('aerosync.db')
    cursor = conn.cursor()

    # 1. Drop existing tables for a clean slate every time you test
    cursor.execute('DROP TABLE IF EXISTS bookings')
    cursor.execute('DROP TABLE IF EXISTS flights')

    # 2. Build the FLIGHTS Table (The Environment)
    # Notice the columns built specifically for your agents!
    cursor.execute('''
    CREATE TABLE flights (
        flight_id TEXT PRIMARY KEY,
        route TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        total_capacity INTEGER NOT NULL,
        available_seats INTEGER NOT NULL,          -- For the Swarm to check 
        final_dynamic_price_inr REAL NOT NULL,     -- For the Swarm to evaluate [cite: 11]
        status TEXT DEFAULT 'Scheduled',           -- The Disruption Generator will flip this to 'CANCELLED' 
        version INTEGER DEFAULT 1                  -- For Concurrency Locks (Race Condition protection)
    )
    ''')

    # 3. Build the BOOKINGS Table (The Ledger & Manifest)
    cursor.execute('''
    CREATE TABLE bookings (
        booking_id TEXT PRIMARY KEY,
        flight_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,                    -- Which Swarm bot bought this?
        agent_persona TEXT NOT NULL,               -- Budget, Corporate, or Festival?
        price_paid REAL NOT NULL,
        status TEXT DEFAULT 'CONFIRMED',           -- The Coordinator will change this if reallocated
        timestamp TEXT NOT NULL,
        FOREIGN KEY (flight_id) REFERENCES flights (flight_id)
    )
    ''')

    # 4. Seed the Database with some test flights for today
    today = datetime.now()
    test_flights = [
        # flight_id, route, dep_time, capacity, avail_seats, price
        ('6E-101', 'DEL-BOM', (today + timedelta(hours=4)).isoformat(), 180, 180, 5500.0),
        ('6E-102', 'DEL-BOM', (today + timedelta(hours=8)).isoformat(), 180, 180, 4800.0),
        ('6E-205', 'DEL-CCU', (today + timedelta(days=1)).isoformat(), 180, 180, 6200.0)
    ]

    cursor.executemany('''
        INSERT INTO flights (flight_id, route, departure_time, total_capacity, available_seats, final_dynamic_price_inr)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', test_flights)

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully. Shared Memory is online.")

if __name__ == "__main__":
    initialize_database()