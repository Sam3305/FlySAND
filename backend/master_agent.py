import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

import motor.motor_asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] MasterAgent — %(message)s")
log = logging.getLogger("mcp.master")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "aerosync")

AGENT_TOOL_MAP = {
    "evaluate_route_yields": "yield",
    "draft_financial_brief": "cfo",
    "plan_network": "network",
    "optimize_fuel": "fuel",
}

class GeminiMasterAgent:
    def __init__(self, status_callback=None):
        self.gemini = genai.Client(api_key=GEMINI_API_KEY)
        self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        self.db = self.db_client[MONGO_DB]
        self.logs_dir = Path(__file__).resolve().parent / "agent_logs"
        self.logs_dir.mkdir(exist_ok=True)
        self.status_callback = status_callback
        self.agent_results = {}

    def _update_status(self, agent: str, field: str, value):
        if self.status_callback:
            self.status_callback(agent, field, value)

    def _write_agent_log(self, agent_name: str, content: str):
        filename = self.logs_dir / f"{agent_name}_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {agent_name.upper()} Agent Log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(content)
        log.info(f"Wrote per-agent log: {filename}")

    async def commit_pricing_to_db(self, flight_id: str, new_fare: float, reason: str) -> str:
        log.info(f"DB COMMIT: Flight {flight_id} -> ₹{new_fare} (Reason: {reason})")
        await self.db.live_flights.update_one(
            {"_id": flight_id},
            {
                "$set": {"current_pricing.ml_fare_inr": float(new_fare)},
                "$push": {
                    "pricing_history": {
                        "timestamp": datetime.now(),
                        "fare_inr": float(new_fare),
                        "source": "MasterAgent",
                        "reason": reason
                    }
                }
            }
        )
        return f"Successfully committed ₹{new_fare} for {flight_id}."

    async def execute_schedule_reduction(self, route: str, slot_to_cut: str, reason: str) -> str:
        log.info(f"DB COMMIT: Schedule Reduction {route} (Slot {slot_to_cut}) => {reason}")
        if "-" not in route:
            return "Error: Invalid route format. Must be ORIGIN-DEST."
        origin, dest = route.split("-")
        
        cursor = self.db.live_flights.find({
            "origin": origin,
            "destination": dest,
            "slot": slot_to_cut,
            "status": "scheduled"
        })
        flights = await cursor.to_list(length=None)
        
        cancelled = 0
        for fl in flights:
            capacity = fl.get("inventory", {}).get("capacity", 186)
            sold = fl.get("inventory", {}).get("sold", 0)
            lf = (sold / capacity) if capacity else 0
            
            # Cancellation Threshold < 10%
            if lf < 0.10:
                dep_date = fl.get("departure_date")
                next_flight = await self.db.live_flights.find_one({
                    "origin": origin,
                    "destination": dest,
                    "status": "scheduled",
                    "departure_date": {"$gte": dep_date},
                    "_id": {"$ne": fl["_id"]}
                }, sort=[("departure_date", 1)])
                
                if next_flight:
                    next_avail = next_flight.get("inventory", {}).get("available", 0)
                    if next_avail >= sold:
                        # Passenger Migration
                        if sold > 0:
                            await self.db.bookings.update_many(
                                {"flight_id": str(fl["_id"])},
                                {"$set": {"flight_id": str(next_flight["_id"])}}
                            )
                            await self.db.live_flights.update_one(
                                {"_id": next_flight["_id"]},
                                {
                                    "$inc": {
                                        "inventory.sold": sold,
                                        "inventory.available": -sold
                                    }
                                }
                            )
                        
                        await self.db.live_flights.update_one(
                            {"_id": fl["_id"]},
                            {"$set": {"status": "cancelled", "reason": f"Auto-Op: {reason}"}}
                        )
                        cancelled += 1
                        
        return f"Evaluated {len(flights)} flights. Cancelled {cancelled} flights under 10% LF and migrated passengers via Protection Protocol."

    async def execute_aircraft_swap(self, route: str, slot: str, new_aircraft: str, new_capacity: int, reason: str) -> str:
        log.info(f"DB COMMIT: Aircraft Swap {route} (Slot {slot}) to {new_aircraft} => {reason}")
        if "-" not in route:
            return "Error: Invalid route format."
        origin, dest = route.split("-")
        
        result = await self.db.live_flights.update_many(
            {
                "origin": origin, 
                "destination": dest, 
                "slot": slot, 
                "status": "scheduled",
                "inventory.sold": {"$lte": new_capacity}
            },
            {
                "$set": {
                    "inventory.capacity": new_capacity,
                    "inventory.aircraft": new_aircraft
                }
            }
        )
        return f"Successfully swapped aircraft to {new_aircraft} for {result.modified_count} eligible flights on {route} (Slot: {slot})."

    async def dispatch_fuel_tankering(self, route: str, extra_fuel_kg: int, reason: str) -> str:
        log.info(f"DB COMMIT: Fuel Tankering {route} (+{extra_fuel_kg}kg) => {reason}")
        if "-" not in route:
            return "Error: Invalid route format."
        origin, dest = route.split("-")
        
        result = await self.db.live_flights.update_many(
            {
                "origin": origin, 
                "destination": dest, 
                "status": "scheduled"
            },
            {
                "$set": {"dispatch.tankered_fuel_kg": extra_fuel_kg},
                "$push": {
                    "dispatch.remarks": f"Auto-Op: Uplift {extra_fuel_kg}kg extra fuel. {reason}"
                }
            }
        )
        return f"Successfully dispatched tankering orders (+{extra_fuel_kg}kg) to {result.modified_count} flights on {route}."

    async def log_agent_discussion(self, log_content: str) -> str:
        filename = self.logs_dir / f"master_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(log_content)
        log.info(f"Logged master agent discussion to {filename}")
        return f"Logged discussion to {filename}"

    async def run(self):
        if not GEMINI_API_KEY:
            log.error("GEMINI_API_KEY is not set.")
            return

        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            servers = {
                "yield": ["-m", "mcp_servers.yield_manager_mcp"],
                "cfo": ["-m", "mcp_servers.cfo_narrator_mcp"],
                "network": ["-m", "mcp_servers.network_planner_mcp"],
                "fuel": ["-m", "mcp_servers.fuel_procurement_mcp"]
            }
            sessions = {}
            for name, args in servers.items():
                self._update_status(name, "status", "initializing")
                try:
                    params = StdioServerParameters(command="python", args=args, env=os.environ.copy())
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    sessions[name] = session
                    self._update_status(name, "status", "online")
                except Exception as e:
                    log.error(f"Failed to initialize {name}: {e}")
                    self._update_status(name, "status", "error")

            log.info("All 4 MCP Sub-Agent Servers Initialized. Gemini Master taking command.")
            
            system_prompt = """
            You are the Supreme Master Agent orchestrating an AI-managed airline called AeroSync-India.
            You are operating in FULL EXECUTION MODE. You do not just advise; you manipulate the physical schedules of aircraft.
            
            TOOLS AVAILABLE TO YOU:
            1. evaluate_route_yields: Queries Yield Manager for pricing logic.
            2. draft_financial_brief: Queries CFO Narrator for finance health JSON.
            3. plan_network: Queries Network Planner for scheduling optimizations JSON.
            4. optimize_fuel: Queries Fuel Procurement for tankering economics JSON.
            5. commit_pricing_to_db: Authorizes the Yield Manager to mutate live airfares.
            6. execute_schedule_reduction: Cancels flights to reduce frequency (has built-in >10% pax migration safeguards).
            7. execute_aircraft_swap: Modifies the live fleet capacity mapping.
            8. dispatch_fuel_tankering: Uplifts excessive fuel strictly based on Fuel Optimizer limits.
            9. log_agent_discussion: Saves your final narrative.
            
            YOUR DIRECTIVES:
            1. Parse the JSON insights of the Network Planner first. If it commands cuts or fleet swaps, you MUST execute `execute_schedule_reduction` or `execute_aircraft_swap` appropriately! Do not be timid. Action the cuts!
            2. Parse the Fuel JSON. Run `dispatch_fuel_tankering` for profitable routes.
            3. Log your actions transparently using `log_agent_discussion`.
            """

            tools = [
                types.Tool(function_declarations=[
                    types.FunctionDeclaration(
                        name="evaluate_route_yields", 
                        description="Analyzes flight margins. Returns JSON.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={"max_flights": types.Schema(type=types.Type.INTEGER)})
                    ),
                    types.FunctionDeclaration(name="draft_financial_brief", description="Returns finance overview."),
                    types.FunctionDeclaration(name="plan_network", description="Returns network slot analysis and right-sizing logic JSON."),
                    types.FunctionDeclaration(name="optimize_fuel", description="Returns fuel tankering economics and risk JSON."),
                    types.FunctionDeclaration(
                        name="commit_pricing_to_db", 
                        description="Commits a finalized price to MongoDB.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={
                            "flight_id": types.Schema(type=types.Type.STRING),
                            "new_fare": types.Schema(type=types.Type.NUMBER),
                            "reason": types.Schema(type=types.Type.STRING)
                        }, required=["flight_id", "new_fare", "reason"])
                    ),
                    types.FunctionDeclaration(
                        name="execute_schedule_reduction", 
                        description="Cancels severely underperforming flights and triggers the Passenger Migration system.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={
                            "route": types.Schema(type=types.Type.STRING, description="e.g. BOM-DEL"),
                            "slot_to_cut": types.Schema(type=types.Type.STRING, description="e.g. C"),
                            "reason": types.Schema(type=types.Type.STRING)
                        }, required=["route", "slot_to_cut", "reason"])
                    ),
                    types.FunctionDeclaration(
                        name="execute_aircraft_swap", 
                        description="Downgrades or upgrades fleet gauge safely.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={
                            "route": types.Schema(type=types.Type.STRING),
                            "slot": types.Schema(type=types.Type.STRING),
                            "new_aircraft": types.Schema(type=types.Type.STRING, description="e.g. A320neo"),
                            "new_capacity": types.Schema(type=types.Type.INTEGER, description="e.g. 186"),
                            "reason": types.Schema(type=types.Type.STRING)
                        }, required=["route", "slot", "new_aircraft", "new_capacity", "reason"])
                    ),
                    types.FunctionDeclaration(
                        name="dispatch_fuel_tankering", 
                        description="Dispatches tankering limits onto actual ops.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={
                            "route": types.Schema(type=types.Type.STRING),
                            "extra_fuel_kg": types.Schema(type=types.Type.INTEGER),
                            "reason": types.Schema(type=types.Type.STRING)
                        }, required=["route", "extra_fuel_kg", "reason"])
                    ),
                    types.FunctionDeclaration(
                        name="log_agent_discussion", 
                        description="Saves a master log to the file system.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={"log_content": types.Schema(type=types.Type.STRING)}, required=["log_content"])
                    )
                ])
            ]

            chat = self.gemini.chats.create(
                model='gemini-2.5-flash', 
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt, 
                    tools=tools,
                    temperature=0.1
                )
            )

            log.info("Master Agent initiating full autonomous execution sweep...")
            prompt = "Scan the environment. Query Network, Fuel, CFO, and Yield. Automatically execute Schedule Reductions, Fleet Swaps, and Fuel Dispatch based on the precise recommendations from the sub-agents. Then summarize all your actions into the master log."
            
            response = chat.send_message(prompt)
            
            while response.function_calls:
                function_responses = []
                for call in response.function_calls:
                    name = call.name
                    args = call.args
                    log.info(f"Gemini explicitly invoked tool: {name}")

                    agent_name = AGENT_TOOL_MAP.get(name)
                    if agent_name:
                        self._update_status(agent_name, "status", "queried")
                    
                    result_str = ""
                    try:
                        if name == "evaluate_route_yields":
                            limit = args.get("max_flights", 5)
                            mcp_res = await sessions["yield"].call_tool("evaluate_route_yields", {"max_flights": limit})
                            result_str = str(mcp_res.content[0].text if isinstance(mcp_res.content, list) else mcp_res.content)
                            self.agent_results["yield"] = result_str
                            self._write_agent_log("yield", result_str)
                            self._update_status("yield", "status", "responded")
                            self._update_status("yield", "last_run", datetime.now().isoformat())
                            self._update_status("yield", "last_result", result_str[:300])
                        elif name == "draft_financial_brief":
                            mcp_res = await sessions["cfo"].call_tool("draft_financial_brief")
                            result_str = str(mcp_res.content[0].text if isinstance(mcp_res.content, list) else mcp_res.content)
                            self.agent_results["cfo"] = result_str
                            self._write_agent_log("cfo", result_str)
                            self._update_status("cfo", "status", "responded")
                            self._update_status("cfo", "last_run", datetime.now().isoformat())
                            self._update_status("cfo", "last_result", result_str[:300])
                        elif name == "plan_network":
                            mcp_res = await sessions["network"].call_tool("plan_network")
                            result_str = str(mcp_res.content[0].text if isinstance(mcp_res.content, list) else mcp_res.content)
                            self.agent_results["network"] = result_str
                            self._write_agent_log("network", result_str)
                            self._update_status("network", "status", "responded")
                            self._update_status("network", "last_run", datetime.now().isoformat())
                            self._update_status("network", "last_result", result_str[:300])
                        elif name == "optimize_fuel":
                            mcp_res = await sessions["fuel"].call_tool("optimize_fuel")
                            result_str = str(mcp_res.content[0].text if isinstance(mcp_res.content, list) else mcp_res.content)
                            self.agent_results["fuel"] = result_str
                            self._write_agent_log("fuel", result_str)
                            self._update_status("fuel", "status", "responded")
                            self._update_status("fuel", "last_run", datetime.now().isoformat())
                            self._update_status("fuel", "last_result", result_str[:300])
                        elif name == "commit_pricing_to_db":
                            result_str = await self.commit_pricing_to_db(args.get("flight_id"), args.get("new_fare"), args.get("reason"))
                        elif name == "execute_schedule_reduction":
                            result_str = await self.execute_schedule_reduction(args.get("route"), args.get("slot_to_cut"), args.get("reason"))
                        elif name == "execute_aircraft_swap":
                            result_str = await self.execute_aircraft_swap(args.get("route"), args.get("slot"), args.get("new_aircraft"), int(args.get("new_capacity")), args.get("reason"))
                        elif name == "dispatch_fuel_tankering":
                            result_str = await self.dispatch_fuel_tankering(args.get("route"), int(args.get("extra_fuel_kg")), args.get("reason"))
                        elif name == "log_agent_discussion":
                            result_str = await self.log_agent_discussion(args.get("log_content"))
                        else:
                            result_str = "Error: Unknown tool."
                    except Exception as e:
                        log.error(f"Tool execution failed: {e}")
                        result_str = f"Error: {e}"
                        if agent_name:
                            self._update_status(agent_name, "status", "error")
                        
                    function_responses.append(types.Part.from_function_response(
                        name=name,
                        response={"result": result_str}
                    ))
                    
                response = chat.send_message(function_responses)

            for ag in ("yield", "cfo", "network", "fuel"):
                if ag in sessions:
                    self._update_status(ag, "status", "idle")
                
            log.info("Master Agent Execution Protocol Complete. Final Output:")
            log.info(response.text)


if __name__ == "__main__":
    agent = GeminiMasterAgent()
    asyncio.run(agent.run())
