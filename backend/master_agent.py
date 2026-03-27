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
            You have access to specialized Sub-Agents over the Model Context Protocol (MCP).
            
            TOOLS AVAILABLE TO YOU:
            1. evaluate_route_yields: Queries Yield Manager for pricing. Returns JSON.
            2. draft_financial_brief: Queries CFO Narrator for finance health. Returns JSON.
            3. plan_network: Queries Network Planner for scheduling and aircraft right-sizing. Returns JSON.
            4. optimize_fuel: Queries Fuel Procurement for tankering analysis. Returns JSON.
            5. commit_pricing_to_db: Commits an approved price to MongoDB.
            6. log_agent_discussion: Saves a detailed markdown log of your thought process.
            
            YOUR DIRECTIVES:
            1. Scrutinize all sub-agent JSON arrays carefully.
            2. Execute commit_pricing_to_db for specific airfares only if they make fiscal sense.
            3. In your final report, highlight the actions taken by fuel and network planners.
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

            log.info("Master Agent initiating full system sweep...")
            prompt = "Act on the current environment. Give me the CFO status, the Network map, the Fuel op, and Yield. Summarize them into a master log."
            
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
                
            log.info("Master Agent Protocol Complete. Final Output:")
            log.info(response.text)


if __name__ == "__main__":
    agent = GeminiMasterAgent()
    asyncio.run(agent.run())
