# trip_orchestrator.py
import json
import operator
from typing import Annotated, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt

from trip_info_graph import destination_graph, APPROVE_SIGNALS
from leg_transportation_graph import transport_graph
from lodging_graph import lodging_graph

# ---------- Unified state ----------
# Superset of DestinationResearchState + TransportPlanningState + LodgingPlanningState.
# All three subgraphs are compiled WITHOUT their own checkpointer (see each file's
# `else: graph = builder.compile()` branch), so they inherit the orchestrator's
# checkpointer when nested as nodes here — that's what lets interrupt()/Command(resume=...)
# propagate up to this single top-level thread instead of needing three separate ones.

class OrchestratorState(TypedDict):
    # --- trip_info_graph (destination_graph) ---
    trip_preferences: str
    max_analysts: int
    analysts: list
    sections: Annotated[list, operator.add]
    human_analyst_feedback: Optional[str]
    destination_candidates: list
    finalized_destinations: list
    review_decision: Optional[str]
    ordered_destinations: list[dict]
    order_decision: Optional[str]
    order_feedback: Optional[str]
    trip_start_date: Optional[str]
    trip_end_date: Optional[str]
    dated_itinerary: list[dict]
    date_decision: Optional[str]
    date_feedback: Optional[str]

    # --- bridge node ---
    loyalty_programmes: list[str]

    # --- leg_transportation_graph (transport_graph) ---
    home_city: str
    home_country: str
    return_city: str
    return_country: str
    legs: list[dict]
    finalized_legs: Annotated[list[dict], operator.add]

    # --- lodging_graph (lodging_graph) ---
    stay_legs: list[dict]
    finalized_stays: Annotated[list[dict], operator.add]


# ---------- Bridge node ----------

def collect_loyalty_programmes(state: OrchestratorState):
    """Only gap between transportation's output and lodging's input — nothing upstream
    produces loyalty_programmes, so ask once here rather than defaulting silently to []
    and quietly skipping MaxMyPoint enrichment for every traveler."""
    raw = interrupt({
        "type": "loyalty_programmes_request",
        "message": "Any hotel loyalty programmes you hold? Comma-separated (e.g. "
                   "'Marriott Bonvoy, Hyatt'), or 'skip' for none.",
    })
    if raw.strip().lower() in APPROVE_SIGNALS or raw.strip().lower() == "skip":
        return {"loyalty_programmes": []}
    return {"loyalty_programmes": [p.strip() for p in raw.split(",") if p.strip()]}


# ---------- Graph wiring ----------

builder = StateGraph(OrchestratorState)
builder.add_node("trip_info", destination_graph)
builder.add_node("collect_loyalty_programmes", collect_loyalty_programmes)
builder.add_node("transportation", transport_graph)
builder.add_node("lodging", lodging_graph)

builder.add_edge(START, "trip_info")
builder.add_edge("trip_info", "collect_loyalty_programmes")
builder.add_edge("collect_loyalty_programmes", "transportation")
builder.add_edge("transportation", "lodging")
builder.add_edge("lodging", END)

# For LangSmith Studio (no __main__ execution) — matches the pattern in the other
# three files where the module-level `graph`/`transport_graph`/`lodging_graph` name
# is what langgraph.json points at.
orchestrator = builder.compile()

INITIAL_STATE = {
    # trip_info
    "trip_preferences": "",
    "max_analysts": 5,
    "analysts": [],
    "sections": [],
    "human_analyst_feedback": "",
    "destination_candidates": [],
    "finalized_destinations": [],
    "ordered_destinations": [],
    "dated_itinerary": [],
    # bridge
    "loyalty_programmes": [],
    # transportation
    "legs": [],
    "finalized_legs": [],
    # lodging
    "stay_legs": [],
    "finalized_stays": [],
}

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "1"}}
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    initial_state = {
        **INITIAL_STATE,
        "trip_preferences": input("""
    Please tell about what kind of traveler you are and what you are looking/planning for in this trip:
        1. Budget/General Traveling Preferences
        2. Any tentative dates/months + weather preferences
        3. Any bucket list locations / inspirations you already have in mind
        4. How many people are on this trip
        5. Activities and foods that you enjoy
        6. Any other preferences you have while traveling, tell us the story of what you would like it to be
    """),
    }
    result = graph.invoke(initial_state, config=config)

    while "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        interrupt_type = interrupt_data["type"]

        # ---------- trip_info_graph interrupts ----------
        if interrupt_type == "human_feedback":
            print("Proposed analyst panel:")
            for a in interrupt_data.get("analysts", []):
                print(f"  - {a}")
            resume_value = input("Approve this panel? (y = approve, anything else = revise): ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "review_destinations":
            print("Candidates:")
            for i, c in enumerate(interrupt_data["destination_candidates"]):
                print(f"  [{i}] {c['city']}, {c['country']} — {c['recommended_season']}, "
                      f"{c['recommended_duration_days_min']}-{c['recommended_duration_days_max']} days")
            resume_value = input("Approve all (blank/approve), pick some (e.g. '0,2' or 'Kyoto, Lisbon'), "
                                 "or describe what you'd change: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "order_review":
            print("Proposed order:")
            for i, s in enumerate(interrupt_data["ordered_destinations"]):
                print(f"  [{i}] {s['city']}, {s['country']}")
            resume_value = input("Approve (blank/approve), drop legs (e.g. 'drop: Busan, Jeju'), "
                                 "or describe other changes: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "start_date_request":
            print("Order finalized:")
            for i, s in enumerate(interrupt_data["ordered_destinations"]):
                print(f"  [{i}] {s['city']}")
            resume_value = input("Earliest departure, latest return (YYYY-MM-DD, YYYY-MM-DD): ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "date_review":
            print("Proposed dates:")
            for s in interrupt_data["dated_itinerary"]:
                print(f"  {s['city']}: {s['depart_date']} → {s['return_date']} ({s['duration_days']}d)")
            resume_value = input("Approve dates (blank/approve), or describe changes: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        # ---------- bridge interrupt ----------
        elif interrupt_type == "loyalty_programmes_request":
            print(f"\n{interrupt_data['message']}")
            resume_value = input("> ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        # ---------- leg_transportation_graph interrupts ----------
        elif interrupt_type == "home_context_request":
            print(f"\n{interrupt_data['message']}")
            print(f"  First stop: {interrupt_data['first_stop']}")
            print(f"  Last stop:  {interrupt_data['last_stop']}")
            resume_value = input("> ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "transport_mode_review":
            print("\nProposed legs:")
            for i, leg in enumerate(interrupt_data["legs"]):
                print(f"  [{i}] {leg['origin']} → {leg['destination']} "
                      f"({leg['depart_date']}) — modes: {leg['modes_requested']}")
            resume_value = input(
                "\nApprove all (blank/approve), or override e.g. '0: flight,train | 1: car': "
            )
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "leg_transport_review":
            print(f"\n{interrupt_data['message']}")
            if interrupt_data.get("recommendation_reasoning"):
                print(f"  Recommendation: {interrupt_data['recommendation_reasoning']}")
            for i, opt in enumerate(interrupt_data["options"]):
                print(f"  [{i}] {opt['mode']} — {opt.get('provider')} — "
                      f"{opt.get('price_estimate')} — {opt.get('duration')}")
            resume_value = input("Your choice: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        # ---------- lodging_graph interrupts ----------
        elif interrupt_type == "stay_type_review":
            print("\nProposed stops:")
            for i, leg in enumerate(interrupt_data["stay_legs"]):
                print(f"  [{i}] {leg['city']} ({leg['check_in']} → {leg['check_out']}) — "
                      f"types: {leg['stay_types_requested']}")
            resume_value = input("\nApprove all (blank/approve), or override e.g. '0: hostel,homestay | 2: hotel': ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "stay_review":
            print(f"\n{interrupt_data['message']}")
            if interrupt_data.get("recommendation_reasoning"):
                print(f"  Recommendation: {interrupt_data['recommendation_reasoning']}")
            for i, opt in enumerate(interrupt_data["options"]):
                pn = f"${opt['price_per_night_usd']:,.2f}/night" if opt.get(
                    "price_per_night_usd") is not None else "night rate n/a"
                tot = f"${opt['total_cost_usd']:,.2f} total" if opt.get("total_cost_usd") is not None else "total n/a"
                if opt.get("price_note"):
                    tot = opt["price_note"]
                print(f"  [{i}] {opt['type']} ({opt['brand_classification']}) — {opt.get('name')} — {pn} / {tot} — "
                      f"{opt['confidence']}")
            resume_value = input("Your choice: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        else:
            raise ValueError(f"Unhandled interrupt type: {interrupt_type}")

    print("\n=== Trip finalized ===")
    print("\nFinalized transportation legs:")
    for leg in result.get("finalized_legs", []):
        sel = leg["selected"]
        if sel:
            print(f"  {leg['origin']} → {leg['destination']}: {sel['mode']} via {sel.get('provider')} "
                  f"({sel.get('price_estimate')})")
        else:
            print(f"  {leg['origin']} → {leg['destination']}: unresolved (skipped)")

    print("\nFinalized stays:")
    for leg in result.get("finalized_stays", []):
        sel = leg["selected"]
        if sel:
            tot = f"${sel['total_cost_usd']:,.2f} total" if sel.get("total_cost_usd") is not None else "total n/a"
            print(f"  {leg['city']}: {sel['type']} — {sel.get('name')} ({tot}, {sel['confidence']})")
        else:
            print(f"  {leg['city']}: unresolved (skipped)")
else:
    graph = builder.compile()