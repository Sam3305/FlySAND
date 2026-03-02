const express = require('express');
const cors = require('cors');
const mysql = require('mysql2/promise');
const redis = require('redis');

const app = express();

// --- 1. MIDDLEWARE ---
app.use(cors()); // Allows Frontend to talk to Backend
app.use(express.json()); // Allows Backend to read JSON data

// --- 2. MYSQL DATABASE CONNECTION ---
const pool = mysql.createPool({
    host: 'localhost',
    user: 'root', 
    password: '12345', // ⚠️ CHANGE THIS TO YOUR MYSQL PASSWORD
    database: 'aerosync',
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0
});

// --- 3. REDIS CACHE SETUP ---
let isRedisConnected = false;
const redisClient = redis.createClient();

redisClient.on('error', (err) => {
    console.log('⚠️ Redis is not running. Caching will be skipped.');
});

redisClient.connect()
    .then(() => {
        isRedisConnected = true;
        console.log('🟢 Redis Cache Connected');
    })
    .catch(() => {
        isRedisConnected = false;
    });

// ==========================================
// API ROUTES
// ==========================================

// 📍 ROUTE 1: THE SECURE LOGIN API
app.post('/api/login', async (req, res) => {
    const { username, password } = req.body; 

    try {
        const [users] = await pool.query(
            'SELECT username, role FROM users WHERE username = ? AND password = ?', 
            [username, password]
        );

        if (users.length > 0) {
            res.json({ success: true, role: users[0].role, username: users[0].username });
        } else {
            res.status(401).json({ success: false, message: "Invalid credentials" });
        }
    } catch (err) {
        console.error("Login Error:", err);
        res.status(500).json({ success: false, message: "Database error" });
    }
});

// 📍 ROUTE 2: FETCH AIRPORTS (WITH REDIS CACHING)
app.get('/api/airports', async (req, res) => {
    const cacheKey = 'aerosync_airports';

    try {
        // Step A: Check Redis Cache First (If Redis is running)
        if (isRedisConnected) {
            const cachedData = await redisClient.get(cacheKey);
            if (cachedData) {
                console.log("Serving airports from Redis Cache! ⚡");
                return res.json(JSON.parse(cachedData));
            }
        }

        // Step B: Cache Miss or Redis Offline. Fetch from MySQL Workbench
        console.log("Querying MySQL database for airports... 🗄️");
        const [airports] = await pool.query('SELECT iata_code as code, city, airport_name as name FROM airports');
        
        // Step C: Save result to Redis for 1 hour (3600 seconds)
        if (isRedisConnected) {
            await redisClient.setEx(cacheKey, 3600, JSON.stringify(airports));
        }
        
        res.json(airports);
    } catch (err) {
        console.error("Airport Fetch Error:", err);
        res.status(500).json({ error: 'Failed to fetch airports' });
    }
});

// 📍 ROUTE 3: BUSINESS ANALYST METRICS
app.get('/api/analytics', async (req, res) => {
    try {
        // In a final production app, you would run SQL SUM() and COUNT() queries here.
        const analyticsData = {
            totalRevenue: "₹12,45,900",
            revenueTrend: "+5.2%",
            activeFlights: 142,
            surchargesActive: 18,
            avgBreakEvenFuel: "3,120 kg"
        };
        res.json(analyticsData);
    } catch (err) {
        res.status(500).json({ error: 'Failed to load analytics' });
    }
});

// 📍 ROUTE 4: DYNAMIC PRICING & PHYSICS SIMULATION
app.post('/api/simulate-boarding-pass', (req, res) => {
    const { passengerName, seat, altitude, windSpeed, baseFare } = req.body;

    let fuelBurn = 3000.00; 
    let surcharge = 0;
    let logic = "Standard Operational Cost";
    let surchargePercent = 0;

    // Check Altitude & Wind Constraints (Group 3 Physics Logic)
    if (altitude === "25000" && windSpeed < 0) {
        fuelBurn = 3359.76; 
        surchargePercent = 15;
        surcharge = baseFare * 0.15; // 15% Dynamic Surcharge
        logic = "High Burn Surcharge";
    }

    const finalAmount = baseFare + surcharge;

    res.json({
        status: "CONFIRMED",
        finalAmount: finalAmount.toFixed(2),
        simulatedAltitude: `${altitude} ft`,
        simulatedWind: `${windSpeed} kts`,
        predictedFuelBurn: `${fuelBurn.toFixed(2)} kg`,
        pricingLogic: logic,
        surchargePercent: surchargePercent
    });
});

// --- 4. START THE SERVER ---
const PORT = 5000;
app.listen(PORT, () => {
    console.log(`\n=========================================`);
    console.log(`🚀 AeroSync Backend Running on http://localhost:${PORT}`);
    console.log(`=========================================\n`);
});