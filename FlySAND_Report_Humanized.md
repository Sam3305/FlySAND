# A PROJECT REPORT
on
"FlySAND"
(FlySAND - Autonomous AI-Operated Airline Platform)

Submitted to
KIIT Deemed to be University

In Partial Fulfilment of the Requirement for the Award of
BACHELOR'S DEGREE IN COMPUTER SCIENCE ENGINEERING

BY
Akash Kumar Singh (Roll No. 23051080)
Arsh Kumar Singh (Roll No. 23052312)
Samarth Verma (Roll No. 2305483)
Pratik Bal (Roll No. 23051206)
Kalpataru Nanda (Roll No. 2305384)
Rishi Kumar Sinha (Roll No. 2305877)

UNDER THE GUIDANCE OF
Mrs. Aradhana Behura 

SCHOOL OF COMPUTER SCIENCE ENGINEERING
KALINGA INSTITUTE OF INDUSTRIAL TECHNOLOGY
BHUBANESWAR, ODISHA - 751024
March 2026

---

### CERTIFICATE
This is to certify that the project entitled "FLYSAND" submitted by Akash Kumar Singh, Arsh Kumar Singh, Samarth Verma, Pratik Bal, Kalpataru Nanda, and Rishi Kumar Sinha is a record of authentic work carried out by them. This was done in partial fulfilment of the requirements for the Bachelor of Engineering degree in Computer Science & Engineering at KIIT Deemed to be University, Bhubaneswar. The work was completed during the 2025-2026 academic year under our supervision.

Mrs. Aradhana Behura
Project Guide
Department of Computer Science Engineering

---

### ACKNOWLEDGEMENTS
We want to say a big thank you to our Project Guide, Ms. Aradhana Behura. Her guidance, feedback, and constant encouragement kept us on track from day one. Honestly, her input really shaped the technical direction of the project.

We also want to thank the School of Computer Engineering at KIIT. Having access to their labs and resources made a huge difference. Building an entire AI airline simulator takes a lot of computing power, so that environment was exactly what we needed.

A quick shoutout to the open-source community too. Projects like FastAPI, MongoDB, Redis, and XGBoost were the building blocks for our work. Also, huge thanks to Google DeepMind for the Gemini API, which effectively runs the brain of our system, and Open-Meteo for giving us free access to the live weather data used in our physics engine.

---

### ABSTRACT
Running an airline is notoriously tough. Profit margins are incredibly tight—usually floating under 4%—even though the logistics involved are insanely complicated. Here in India, Low-Cost Carriers (LCCs) like IndiGo completely dominate the market, especially on the busy Golden Quadrilateral routes connecting Delhi, Mumbai, Chennai, and Kolkata. But airlines face a bunch of headaches: unpredictable fuel prices (which make up a huge chunk of their expenses), ticket pricing systems that can't react fast enough to demand, and manual planning processes that take too long. On top of that, standard cost models ignore how bad weather actually affects fuel burn. We realized there was an opportunity here to build a self-optimizing system driven by AI.

That's where our project, FlySAND, comes in. It’s a fully autonomous airline management platform simulating the Golden Quadrilateral. We built it around four main pieces. First, we made an AeroPhysics Engine that calculates fuel burn across three stages of flight: climb (engines work hardest), cruise (where weather penalties matter most), and descent (mostly gliding). This calculates a hyper-accurate base cost. Next, we trained an XGBoost machine learning model to adjust prices based on real-time weather risks and demand limits. Third, we set up a massive swarm of 100 autonomous agents to simulate passengers trying to buy tickets, grouped into Budget, Leisure, and Business personas. Finally, we tied it all together with Google's Gemini 2.5 Flash using the Model Context Protocol (MCP). We created four AI sub-agents (Yield Manager, CFO, Network Planner, Fuel Procurement) run by a Master Agent to autonomously upgrade planes and change routes without a human ever pressing a button.

**Keywords:** AI Orchestration, Thermodynamic Fuel Modeling, XGBoost Ticket Pricing, Model Context Protocol (MCP), Demand Simulation, Low-Cost Carriers, asyncio Concurrent Booking.

---

### CHAPTER 1: INTRODUCTION
Commercial aviation is a crazy business. You have a massive logistical operation, but at the end of the day, airlines only keep pennies on the dollar. According to IATA, average profit margins barely ever cross 4.7%. Looking at India, Low-Cost Carriers (LCCs) basically own the skies. IndiGo alone controls about 60% of the market. Everyone is fighting for space on the Golden Quadrilateral—the major flight paths connecting Delhi, Mumbai, Kolkata, and Chennai. 

But here's the crazy part: despite all the money on the line, the software running ticket prices is completely outdated. Most airlines still use systems built on ideas from the 1980s. Analysts sit in offices manually adjusting "fare buckets" every week. That’s just way too slow. If a storm is coming or a competitor launches a flash sale, demand changes in minutes, not days. Waiting a week to change prices leads to what McKinsey calls "revenue leakage," where airlines just leave money on the table.

Then there’s fuel, which eats up almost 40% of their operating budget. When planning flights, a lot of software just uses a flat hourly fuel burn rate. That doesn't make any sense because planes burn completely different amounts of fuel when they are fighting gravity to climb, dealing with high headwinds during cruise, or just coasting during descent. Using a flat rate means airlines don't know their true costs. A flight might look profitable on paper but actually lose money because of a heavy monsoon headwind.

We wanted to fix this by throwing modern AI at the problem. Large Language Models (LLMs) like Gemini 2.5 Flash are now smart enough to look at data, understand it, and make actual decisions. By linking these models together using Anthropic's Model Context Protocol (MCP), we built a team of virtual executives that handle pricing, route planning, and finance instantly.

Our project is FlySAND. It’s a six-person effort representing a fully automated airline simulator. Here’s who did what: Samarth Verma built the AeroPhysics Engine, Akash Kumar Singh set up the Agentic AI and MCP logic, Arsh Kumar Singh built the React dashboards, Pratik Bal developed the XGBoost pricing and the passenger swarm, Kalpataru Nanda put together the economics and cost modelling, and Rishi Kumar Sinha tied the entire backend together with FastAPI, MongoDB, and Redis.

---

### CHAPTER 2: BASIC CONCEPTS AND LITERATURE REVIEW

#### 2.1 Machine Learning for Willingness-to-Pay Prediction
Pricing tickets boils down to guessing what someone is willing to pay before the flight takes off. The old school way (like Belobaba's EMSR model from 1987) uses historical data to guess future demand. The problem is that history doesn't account for random events like sudden weather delays or festivals. 
We switched to Gradient Boosting, specifically XGBoost (Chen and Guestrin, 2016). It builds decision trees to find hidden patterns. Our model takes basic airline costs and applies a weather disruption premium on top of it, anywhere from 0% to 25%. We made sure to lock this model so it never drops the price below what the physics engine says the flight costs to run.

#### 2.2 Autonomous Concurrency Models
We needed to simulate thousands of people booking flights at the same time. You can't just run a loop; the math wouldn't look like real life. Real life follows something called a Non-Homogeneous Poisson Process (NHPP), where the booking rate speeds up as the flight date gets closer. We used Python’s `asyncio` to run 100 passenger bots at once. Since they are all fighting for the same seats, we used Redis SETNX locks to ensure two bots couldn't buy the exact same seat at the exact same millisecond.

#### 2.3 Aviation Physics and Thermodynamic Fuel Modelling
The Breguet Range Equation tells us exactly how far a plane can go based on its fuel, drag, and weight. But we broke it down practically. When a plane takes off, the engines are blasting, burning about 85% more fuel than usual. We programmed a 1.85x multiplier for the climb phase. Coming down is the opposite—the engines basically idle, so we use a 0.35x multiplier. The cruise phase in the middle is where weather ruins everything. We programmed equations to look at air density and humidity to calculate how much extra fuel the plane needs to push through a storm.

#### 2.4 Model Context Protocols (MCP)
Early AI agents like AutoGPT were known for getting confused because they tried to do too much at once. The new Model Context Protocol (MCP) fixes this. It creates separated servers where each AI has one specific job. If the Yield Manager AI crashes, the Network Planner AI keeps working fine. It also forces the AI to output clean JSON code so it doesn't break our database. 

---

### CHAPTER 3: PROBLEM STATEMENT AND REQUIREMENT SPECIFICATIONS

#### 3.1 Problem Statement
We noticed three huge unsolved problems in domestic aviation:
1. **Broken Static Pricing:** Ticket prices don't react to atmospheric data or instant demand events.
2. **Fake Cost Floors:** Airlines use average burn rates instead of actual weather-based physics, causing them to accidentally sell tickets at a loss during bad weather.
3. **Slow Network Planning:** Human network planners take a month to decide if a route needs a bigger plane. An AI can do the math and swap the plane in 30 seconds.

Our objective was to build a system that:
* Calculates fuel burn with an accuracy matching actual A320neo manuals.
* Establishes a massive 18-part cost model for exactly how much money a flight costs (CASK).
* Trains an XGBoost model that doesn't just guess prices but calculates weather premiums.
* Runs a 100-bot swarm that acts like real college students and business travelers buying tickets.
* Automates the airline's executive decisions using four Gemini AI agents.

#### 3.2 System Architecture
To make this work without the servers crashing under the weight of the AI and the passenger bots, we had to be very strict about constraints. 
We used Python 3.12 because we needed its advanced `asyncio` tools. We chose MongoDB to store flight data and Motor to handle non-blocking database reads. Redis handles the locking mechanism so duplicate ticket sales don't happen. 

The architecture flows in a circle:
The Database seeds the flights. The Physics and Economics engines calculate the absolute minimum cost to fly. The XGBoost model adds a profit margin. The React frontend and Swarm bots fight to buy the seats. Every 24 hours (in simulation time), the Gemini AI wakes up, checks how much money the airline made, and decides if it needs to cancel flights or upgrade planes.

---

### CHAPTER 4: IMPLEMENTATION

#### 4.1 AeroPhysics Engine (Samarth Verma)
Flat hourly fuel burns are basically a myth invented for basic accounting. Samarth built out the `physics_engine.py` to calculate exactly what is happening in the air. 
For an A320neo, the base burn is 1,989 kg/hr. But during the 20-minute climb, we multiply that by 1.85. During a 25-minute descent, it drops to 0.35. 

For the cruise phase, things get complicated. We use the Tetens Equation to calculate vapor pressure using real temperature data from the Open-Meteo API. If the air is hot and humid, it becomes less dense than the industry standard (ISA). Less dense air means the engines have to work harder, so we apply a density penalty. If there's a thunderstorm (CAPE instability > 1000) or severe icing, we add flat fuel penalties and factor in extra minutes for ATC holding patterns. Every extra kilogram of passenger baggage forces a 0.03 kg fuel penalty. 

#### 4.2 CASK Economics Model (Kalpataru Nanda)
Kalpataru took the physics outputs and draped 18 different real-world expenses over them to figure out the true Cost per Available Seat Kilometer (CASK). 
He used actual data from AAI (Airports Authority of India) to calculate landing fee slabs for Delhi and Mumbai. He programmed in ₹42,000 per block-hour for maintenance and ₹80,000 for plane leases. Interestingly, he also programmed a belly-cargo credit of ₹0.40 per seat-kilometer, since airlines make money hauling freight in the basement of the plane. All of this combines to create the "Cardinal Rule" floor price. A ticket can never, ever be sold below this number.

#### 4.3 Swarm Passenger Simulation (Pratik Bal)
Pratik created a script `swarm.py` to pretend to be 100 different people trying to buy tickets. 
He split them into three groups:
* **Budget Students (40%):** They book three weeks early. If the ticket is over ₹4,500, they just close the app and don't fly.
* **Leisure Travelers (35%):** They book normally, dropping out if the fare goes over ₹7,000.
* **Business Execs (25%):** They realize they have a meeting tomorrow and will pay up to ₹15,000 without blinking.

He used a Poisson distribution for the timing. When the flight is a month away, the bots sleep for 4 to 8 minutes between clicks. In the final 3 days, they panic and spam the server every 5 to 20 seconds. 

#### 4.4 ML Pricing Model (Pratik Bal)
The XGBoost model looks at 15 different factors, like the time of day, how close the flight is, and if it's on a weekend. The most important rule during training was doing a "chronological split." We didn't just shuffle the data. We trained it on past flights and tested it on future flights to prevent temporal data leakage. 

#### 4.5 MCP Agent Ensemble (Akash Kumar Singh)
Akash turned Gemini into an airline board of directors. Using FastMCP, he spawned four background background tasks:
1. **Yield Manager**: Adjusts prices up or down but obeys the 1.40x maximum surge cap.
2. **CFO Narrator**: Reads the profits and writes a financial report summary.
3. **Network Planner**: Looks at empty flights and changes the plane size.
4. **Fuel Procurement**: Optimizes where the planes fuel up to save money.

The Gemini Master Agent talks to these four sub-agents and executes their JSON decisions directly into MongoDB.

#### 4.6 Backend API & Infrastructure (Rishi Kumar Sinha)
Rishi made sure the servers didn't catch fire. He wrote the route handling in FastAPI. The biggest challenge was the race condition where two swarm bots try to buy the last seat. He used Redis SETNX to lock the seat instantly. If bot A gets it, bot B immediately gets an HTTP 409 error and backs off.

#### 4.7 React Frontend (Arsh Kumar Singh)
Arsh built the actual screens users look at using React 18 and Tailwind. He built a pretty slick B2C booking site where you can click a seat map. He also built incredibly detailed dashboards for the Ops team and the CFO to watch the Gemini AI change the network in real time. He wired up WebSockets so that the second a swarm bot buys a ticket, the available seat counter on the website ticks down instantly without having to refresh the page.

---

### CHAPTER 5: STANDARDS ADOPTED
We stuck to standard software engineering practices. All endpoints are RESTful and versioned (e.g., `/api/v1/book`). We used PEP-8 for the Python code and strict TypeScript for the frontend to avoid random bugs. We also used Docker to containerize Redis and MongoDB so anyone on the team could boot the project without dealing with weird dependency issues on their laptops.

For testing, we used `pytest`. We didn't just test if the code ran; we analytically tested the math. For example, test case T01 strictly calculated if the climb fuel burn actually equated to 1989 × 1.85 × 0.333. If the math was off by more than 5 kilograms, the test failed. 

---

### CHAPTER 6: CONCLUSION AND FUTURE SCOPE

Building FlySAND proved that running a commercial airline network doesn't have to be a slow, manual process. By completely rebuilding the foundation of how flight costs are calculated—moving away from flat hourly rates and toward actual weather-based thermodynamics—we fixed the biggest blind spots in revenue management.

Our team successfully merged real aerodynamics, XGBoost machine learning, and concurrent web infrastructure. But the coolest part is absolutely the MCP integration. We proved that if you give a Large Language Model strict rules and mathematical guardrails, it can autonomously manage route expansions and pricing better and faster than a human team evaluating spreadsheets. 

For future scope, there is still a lot of room to play here. We could connect real-time GDS flight feeds to get actual ticket demand data instead of simulating it. We could switch the XGBoost model out for a Reinforcement Learning agent that essentially plays the airline market like a video game to maximize revenue. Finally, hooking up Puppeteer to scrape competitor prices off MakeMyTrip or Goibibo would give the AI an even crazier edge when trying to undercut other airlines. 
