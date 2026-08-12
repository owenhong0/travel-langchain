import json
import operator
import os
import time
from datetime import date
from typing import TypedDict, Optional, List, Annotated

from anthropic import APIStatusError
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, get_buffer_string, AIMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph, MessagesState
from langgraph.types import Send, interrupt, Command
from pydantic import BaseModel, Field, ValidationError, model_validator

load_dotenv()

# llm = ChatAnthropic(model_name="claude-sonnet-5", thinking={"type": "disabled"})  # used for .with_structured_output(...) calls

llm = ChatOpenAI(
    model="anthropic/claude-sonnet-5",
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)
retryable_llm = llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)

def invoke_structured_with_retry(structured_llm, messages, schema, attempts=3):
    last_error = None
    for i in range(attempts):
        try:
            return structured_llm.invoke(messages)
        except ValidationError as e:
            errors = e.errors()
            bad_field = next(
                (err for err in errors if err["type"] == "list_type" and isinstance(err["input"], str)),
                None,
            )
            if bad_field:
                try:
                    return schema.model_validate_json(bad_field["input"])
                except Exception:
                    pass  # fall through to retry
            last_error = e
            time.sleep(2 ** i)
        except APIStatusError as e:
            last_error = e
            time.sleep(2 ** i)
    raise last_error

class Analyst(BaseModel):
    affiliation: str = Field(
        description="Primary affiliation of the analyst.",
    )
    name: str = Field(
        description="Name of the analyst."
    )
    role: str = Field(
        description="Role of the analyst in the context of the topic.",
    )
    description: str = Field(
        description="Description of the analyst focus, concerns, and motives.",
    )
    @property
    def persona(self) -> str:
        return f"Name: {self.name}\nRole: {self.role}\nAffiliation: {self.affiliation}\nDescription: {self.description}\n"

class GraphState(TypedDict):
    trip_preferences: str

class GenerateAnalystsState(TypedDict):
    topic: str # Research topic
    max_analysts: int # Number of analysts
    human_analyst_feedback: str # Human feedback
    analysts: List[Analyst] # Analyst asking questions

class InterviewState(MessagesState):
    max_num_turns: int # Number turns of conversation
    context: Annotated[list, operator.add] # Source docs
    analyst: Analyst # Analyst asking questions
    interview: str # Interview transcript
    sections: list # Final key we duplicate in outer state for Send() API

class OrderedLeg(BaseModel):
    origin_city: str
    destination_city: str
    depart_date: str

class DestinationCandidate(BaseModel):
    city: str
    country: str
    rationale: str
    recommended_season: str = Field(description="Best time of year to visit, e.g. 'Spring (March-May)' or 'Year-round'")
    recommended_duration_days_min: int
    recommended_duration_days_max: int
    rationale: str = Field(description="Why this fits the traveler's stated preferences")
    date: str = Field(description="What date best fits the traveler's stated preferences")
    requires_flight_or_ferry: bool = Field(
        description="True if this destination is an island, archipelago, or otherwise not "
                    "reachable by train/bus/car from the mainland/rest of the region — e.g. "
                    "Jeju, Hawaii, Santorini. False for anywhere reachable by ground transport."
    )

class DestinationOptions(BaseModel):
    candidates: list[DestinationCandidate]

class TravelAnalyst(BaseModel):
    focus_area: str = Field(description="What this analyst prioritizes when evaluating destinations, e.g. 'Adventure & Bucket List', 'Culture & Food', 'Budget & Value'")
    persona_name: str
    description: str = Field(description="What this analyst cares about and pushes back on")

    @property
    def persona(self) -> str:
        return f"Focus: {self.focus_area}\nName: {self.persona_name}\nDescription: {self.description}\n"

class TravelAnalysts(BaseModel):
    analysts: List[TravelAnalyst]

def keep_first(a: str, b: str) -> str:
    return a  # branches write the same unchanged value, so either is fine

class DestinationInterviewState(MessagesState):
    max_num_turns: int
    context: Annotated[list, operator.add]
    analyst: TravelAnalyst
    traveler_preferences: str
    interview: str
    sections: list


class DestinationResearchState(TypedDict):
    trip_preferences: str
    max_analysts: int
    analysts: List[TravelAnalyst]
    sections: Annotated[list, operator.add]
    human_analyst_feedback: str
    destination_candidates: list
    finalized_destinations: list
    review_decision: str
    ordered_destinations: list[dict]
    legs: list[dict]
    review_decision: str  # from review_destinations: "finalize" | "revise"
    order_decision: str  # from review_order: "finalize" | "revise"
    order_feedback: Optional[str]
    trip_start_date: Optional[str]
    trip_end_date: Optional[str]
    dated_itinerary: list[dict]  # ordered_destinations + concrete depart/return per stop
    date_decision: str
    date_feedback: Optional[str]

class DatedStop(BaseModel):
    city: str
    country: str
    depart_date: str
    return_date: str
    duration_days: int
    requires_flight_or_ferry: bool = Field(
        description="Carried over — whether this stop is only reachable by flight/ferry"
    )

class DatedItinerary(BaseModel):
    stops: list[DatedStop]

class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Search query for retrieval.")

search_instructions = SystemMessage(content=f"""You will be given a conversation between an analyst and an expert. 

Your goal is to generate a well-structured query for use in retrieval and / or web-search related to the conversation.

First, analyze the full conversation.

Pay particular attention to the final question posed by the analyst.

Convert this final question into a well-structured web search query""")

analyst_instructions = """You are creating a panel of travel analysts to debate destination
recommendations for a specific traveler.

Traveler's stated preferences:
{trip_preferences}

If this includes "Additional feedback after reviewing initial suggestions," treat that as the
traveler's most important, most recent signal — it means their earlier suggestions didn't fully
fit, so prioritize what changed over what was originally stated when it's unclear which applies.

If the traveler specified a particular country or region, every analyst and every
recommendation must stay within that country/region — treat it as a hard constraint,
not a suggestion. Only suggest destinations outside it if the traveler's preferences
are genuinely open-ended about location.

1. Create {max_analysts} analyst personas, each representing a distinct lens for evaluating
destinations relevant to what this traveler said they care about — for example, one analyst
might focus on adventure and unique experiences, another on culture and food, another on
budget and logistics, another on relaxation and comfort. Tailor the personas to what's
actually in the traveler's preferences rather than using generic categories that don't apply.

2. Examine any editorial feedback that has been optionally provided to guide creation of the analysts: 
        
{human_analyst_feedback}
    
3. Determine the most interesting themes based upon documents and / or feedback above.
                    
4. Pick the top {max_analysts} themes.

5. Assign one analyst to each theme."""


def create_analysts(state: DestinationResearchState):

    structured_llm = llm.with_structured_output(TravelAnalysts)
    system_message = analyst_instructions.format(
        trip_preferences=state["trip_preferences"],
        max_analysts=state.get("max_analysts", 5),
        human_analyst_feedback=state.get('human_analyst_feedback', '')
    )
    analyst = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=system_message),
        HumanMessage(content="Generate the analyst personas."),
    ], TravelAnalysts)
    return {"analysts": analyst.analysts}


GOV_TRAVEL_DOMAINS = [
    "travel.state.gov", "visitusa.com",
    # Europe
    "germany.travel",       # German National Tourist Board
    "france.fr",            # Atout France
    "italia.it",            # Italian National Tourist Board (ENIT)
    "spain.info",           # Spain Tourism Office
    "visitbritain.com",     # VisitBritain
    # Asia
    "japan.travel",         # Japan National Tourism Organization
    "visitkorea.or.kr",     # Korea Tourism Organization
] # add relevant tourism-board domains as you find them for likely destinations
MAGAZINE_DOMAINS = ["travelandleisure.com", "cntraveler.com", "lonelyplanet.com", "afar.com", "nationalgeographic.com"]
UNIQUE_EXPERIENCE_DOMAINS = [
    "atlasobscura.com", "roadsideamerica.com",
    "mrandmrssmith.com",  # boutique/unique hotel guide
    "designhotels.com",   # design-focused unique hotel guide
]

def _tavily_results(data) -> dict:
    """TavilySearch.invoke() can return a plain string (error/status message)
    instead of the expected dict — normalize defensively."""
    if isinstance(data, dict):
        return data
    return {}


def search_gov_travel(state: DestinationInterviewState):
    structured_llm = llm.with_structured_output(SearchQuery)
    messages = [search_instructions] + as_incoming(state["messages"]) + [
        HumanMessage(content="Based on the conversation above, generate a search query.")
    ]
    search_query = invoke_structured_with_retry(structured_llm, messages, SearchQuery)
    tavily_search = TavilySearch(max_results=3, include_domains=GOV_TRAVEL_DOMAINS)
    data = _tavily_results(tavily_search.invoke({"query": search_query.search_query, "include_images": True}))
    image_urls = data.get("images", [])
    docs = data.get("results", [])
    formatted = "\n\n---\n\n".join(
        f'<Document href="{d["url"]}" source_type="government"/>\n{d["content"]}\n</Document>' for d in docs
    )
    return {"context": [formatted]}

def search_travel_magazines(state: DestinationInterviewState):
    structured_llm = llm.with_structured_output(SearchQuery)
    messages = [search_instructions] + state["messages"] + [
        HumanMessage(content="Based on the conversation above, generate a search query.")
    ]
    search_query = invoke_structured_with_retry(structured_llm, messages, SearchQuery)
    tavily_search = TavilySearch(max_results=3, include_domains=MAGAZINE_DOMAINS)
    data = _tavily_results(tavily_search.invoke({"query": search_query.search_query, "include_images": True}))
    image_urls = data.get("images", [])
    docs = data.get("results", [])
    formatted = "\n\n---\n\n".join(
        f'<Document href="{d["url"]}" source_type="magazine"/>\n{d["content"]}\n</Document>' for d in docs
    )
    return {"context": [formatted]}

def search_unique_experiences(state: DestinationInterviewState):
    structured_llm = llm.with_structured_output(SearchQuery)
    messages = [search_instructions] + state["messages"] + [
        HumanMessage(content="Based on the conversation above, generate a search query.")
    ]
    search_query = invoke_structured_with_retry(structured_llm, messages, SearchQuery)
    tavily_search = TavilySearch(max_results=3, include_domains=UNIQUE_EXPERIENCE_DOMAINS)
    data = _tavily_results(tavily_search.invoke({"query": search_query.search_query, "include_images": True}))
    image_urls = data.get("images", [])
    docs = data.get("results", [])
    formatted = "\n\n---\n\n".join(
        f'<Document href="{d["url"]}" source_type="unique_experience"/>\n{d["content"]}\n</Document>' for d in docs
    )
    return {"context": [formatted]}

answer_instructions = """You are a well-traveled expert being interviewed by a travel analyst.

Analyst's focus: {goals}

Answer using only this context, which is tagged by source_type (government, magazine, or unique_experience):
If the traveler specified a particular country or region, only recommend destinations
   within it — do not suggest other countries even if the context surfaces them.

{context}

Guidelines:
1. Recommend 2-3 destinations that fit the analyst's focus area, using only the provided context.
2. For each destination, state the best season to visit and a recommended trip length in days,
   grounded in what the context says (e.g. weather patterns, event seasons, or how much there
   is to do there).
3. For each claim, cite using [1], [2] etc. and note the source_type.
4. Do not introduce destinations or facts not present in the context.
5. List sources at the bottom: [1] source_type — URL"""

def as_incoming(messages: list) -> list:
    """Convert AIMessage entries into HumanMessage so the list ends on a user turn,
    regardless of which persona 'said' it in the interview simulation."""
    converted = []
    for m in messages:
        if isinstance(m, AIMessage):
            converted.append(HumanMessage(content=m.content))
        else:
            converted.append(m)
    return converted

def generate_question(state: DestinationInterviewState):
    analyst = state["analyst"]
    system_message = question_instructions.format(
        persona_name=analyst.persona_name,
        focus_area=analyst.focus_area,
        description=analyst.description,
        trip_preferences=state["traveler_preferences"],
    )
    question = retryable_llm.invoke([SystemMessage(content=system_message)] + as_incoming(state["messages"]))
    return {"messages": [question]}

def generate_answer(state: DestinationInterviewState):
    analyst = state["analyst"]
    messages = state["messages"]
    context = state["context"]
    system_message = answer_instructions.format(goals=analyst.persona, context=context)
    answer = retryable_llm.invoke([SystemMessage(content=system_message)] + as_incoming(messages))
    answer.name = "expert"
    return {"messages": [answer]}

APPROVE_SIGNALS = {"approve", "y", "yes", "all", ""}

def human_feedback(state: DestinationResearchState):
    h_feedback = interrupt({
        "type": "human_feedback",
        "message": "Review the proposed analyst panel. Reply 'approve' to proceed, "
                   "or give feedback to revise the panel.",
        "analysts": [an.persona for an in state["analysts"]],
    })
    return {"human_analyst_feedback": h_feedback}

question_instructions = """You are {persona_name}, a travel analyst focused on: {focus_area}

{description}

You're interviewing a well-traveled expert to find destinations that fit your focus, given
this traveler's preferences: {trip_preferences}

For each destination you discuss, make sure to ask about the best season to visit and how
many days you'd recommend — these should reflect your focus area (e.g. an adventure-focused
recommendation might need more days than a quick cultural weekend).

Ask specific questions, push back if suggestions don't fit your focus, and when satisfied,
end with: "Thank you so much for your help!" """


def save_interview(state: InterviewState):
    """ Save interviews """

    # Get messages
    messages = state["messages"]

    # Convert interview to a string
    interview = get_buffer_string(messages)

    # Save to interviews key
    return {"interview": interview}


def route_messages(state: InterviewState,
                   name: str = "expert"):
    """ Route between question and answer """

    # Get messages
    messages = state["messages"]
    max_num_turns = state.get('max_num_turns', 2)

    # Check the number of expert answers
    num_responses = len(
        [m for m in messages if isinstance(m, AIMessage) and m.name == name]
    )

    # End if expert has answered more than the max turns
    if num_responses >= max_num_turns:
        return 'save_interview'

    # This router is run after each question - answer pair
    # Get the last question asked to check if it signals the end of discussion
    last_question = messages[-2]

    if "Thank you so much for your help" in last_question.content:
        return 'save_interview'
    return "ask_question"

section_writer_instructions = """Write a short section summarizing destination recommendations
from the perspective of: {focus}

Structure:
## <Engaging title for this focus area>
### Recommendations
List 2-3 destinations with a 2-3 sentence rationale each, citing sources as [1], [2].
### Sources
List all cited sources, deduplicated."""

extraction_instructions = """You are given several travel analysts' recommendation sections.
Extract every distinct destination mentioned across all sections into a structured list but exclude any destination outside the country/region the traveler specified, if they
specified one.
For each, include the city, country, recommended season, a recommended duration range in days,
and a synthesized rationale drawing on what the analysts said, noting which source types
(government/magazine/unique_experience) support it. If analysts disagree on season or duration
for the same destination, use your judgment to reconcile into a single reasonable range.

Also determine requires_flight_or_ferry: true if this destination is an island, archipelago, or
otherwise cut off from ground transport to the rest of the region/country (e.g. Jeju, Hawaii,
Santorini, Zanzibar) — false if it's reachable by train/bus/car. Use general knowledge of the
destination's geography plus any cues in the source material (mentions of ferries, domestic
flights, or "island" language)."""

def extract_candidates(state: DestinationResearchState):
    sections = state["sections"]
    formatted = "\n\n".join(sections)
    structured_llm = llm.with_structured_output(DestinationOptions)
    result = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=extraction_instructions),
        HumanMessage(content=formatted),
    ], DestinationOptions)
    return {"destination_candidates": [c.model_dump() for c in result.candidates]}


def write_section(state: InterviewState):
    """ Node to write a section """

    # Get state
    interview = state["interview"]
    context = state["context"]
    analyst = state["analyst"]

    # Write section using either the gathered source docs from interview (context) or the interview itself (interview)
    system_message = section_writer_instructions.format(focus=analyst.description)
    section = retryable_llm.invoke([SystemMessage(content=system_message)] + [
        HumanMessage(content=f"Use this source to write your section: {context}")])

    # Append it to state
    return {"sections": [section.content]}


interview_builder = StateGraph(DestinationInterviewState)
interview_builder.add_node("ask_question", generate_question)
interview_builder.add_node("search_gov_travel", search_gov_travel)
interview_builder.add_node("search_travel_magazines", search_travel_magazines)
interview_builder.add_node("search_unique_experiences", search_unique_experiences)
interview_builder.add_node("answer_question", generate_answer)
interview_builder.add_node("save_interview", save_interview)
interview_builder.add_node("write_section", write_section)

interview_builder.add_edge(START, "ask_question")
interview_builder.add_edge("ask_question", "search_gov_travel")
interview_builder.add_edge("ask_question", "search_travel_magazines")
interview_builder.add_edge("ask_question", "search_unique_experiences")
interview_builder.add_edge("search_gov_travel", "answer_question")
interview_builder.add_edge("search_travel_magazines", "answer_question")
interview_builder.add_edge("search_unique_experiences", "answer_question")
interview_builder.add_conditional_edges("answer_question", route_messages, ["ask_question", "save_interview"])
interview_builder.add_edge("save_interview", "write_section")
interview_builder.add_edge("write_section", END)

def initiate_all_interviews(state: DestinationResearchState):
    # Check if human feedback
    human_analyst_feedback = state.get('human_analyst_feedback', 'approve')
    if human_analyst_feedback.strip().lower() not in APPROVE_SIGNALS:
        return "create_analysts"

    else:
        return [
            Send("conduct_interview", {
                "analyst": analyst,
                "traveler_preferences": state["trip_preferences"],
                "messages": [HumanMessage(
                    content=f"I'm looking for destination ideas — here's what I'm after: {state['trip_preferences']}."
                )],
            })
            for analyst in state["analysts"]
        ]

def _match_candidates(token: str, candidates: list) -> list[int]:
    """Match one comma-split token against candidate indices or city/country names."""
    token = token.strip()
    if not token:
        return []
    if token.isdigit():
        idx = int(token)
        return [idx] if 0 <= idx < len(candidates) else []
    return [
        i for i, c in enumerate(candidates)
        if token.lower() in c["city"].lower() or token.lower() in c["country"].lower()
    ]

def parse_review_response(raw: str, candidates: list) -> dict:
    """Free-text -> finalize/revise decision, mirroring APPROVE_SIGNALS' style."""
    text = (raw or "").strip()

    if text.lower() in APPROVE_SIGNALS:
        return {"type": "finalize", "chosen": candidates}

    tokens = text.split(",")
    matched: set[int] = set()
    for tok in tokens:
        hits = _match_candidates(tok, candidates)
        if not hits:
            # something in here doesn't resolve -> whole input is revision feedback
            return {"type": "revise", "feedback": text}
        matched.update(hits)

    return {"type": "finalize", "chosen": [candidates[i] for i in sorted(matched)]}


def review_destinations(state: DestinationResearchState):
    raw_response = interrupt({
        "type": "review_destinations",
        "message": "Reply 'approve' (or leave blank) to take all of them, list indices or "
                   "city/country names (comma-separated) to pick specific ones, or type "
                   "anything else to revise your preferences.",
        "destination_candidates": state["destination_candidates"],
    })

    candidates = state["destination_candidates"]

    # Back-compat: still accept the old structured dict form too.
    response = raw_response if isinstance(raw_response, dict) else parse_review_response(raw_response, candidates)

    if response["type"] == "finalize":
        return {"finalized_destinations": response["chosen"], "review_decision": "finalize"}
    elif response["type"] == "revise":
        updated_preferences = (
            state["trip_preferences"]
            + f"\n\nAdditional feedback after reviewing initial suggestions: {response['feedback']}"
        )
        return {
            "trip_preferences": updated_preferences,
            "analysts": [], "sections": [], "destination_candidates": [],
            "review_decision": "revise",
        }
    else:
        raise ValueError(f"Unknown response type: {response['type']}")

ordering_instructions = """Given these finalized destinations and the traveler's preferences,
propose the most sensible visiting order — minimize backtracking, respect any stated season/date
constraints, and note the reasoning briefly.

Entry/exit logistics are a hard consideration, not a minor detail: the traveler's trip must
start and end at cities with real international airport access.

The FIRST stop in your output must always be the international gateway city itself — this
represents the arrival leg, even if it's just a short transit stay before heading to the first
"real" destination. If the traveler's plan later returns to that same gateway city for its own
dedicated purpose (shopping, appointments, departure prep), list it AGAIN as a separate stop at
that later point in the sequence — do not merge the arrival transit and the dedicated return
visit into a single entry, even though they're the same city.

Carry forward each destination's requires_flight_or_ferry value unchanged from the input data —
do not recompute or guess it, just preserve what was given.

A destination that requires a dedicated domestic flight to reach (disconnected from the rest of
the route by rail/road) should never be the last stop unless it independently has major
international airport access itself — ending the trip somewhere that requires flying back to a
gateway city before leaving the country defeats the point of a logical sequence. Prefer starting
and ending at the same city, or at minimum ending somewhere with direct international
departures, over an ordering that's geographically tidy but strands the traveler far from an
exit point."""

class OrderedStop(BaseModel):
    city: str
    country: str
    recommended_duration_days: str = Field(description="e.g. '2-4'")
    purpose: str = Field(description="Why this stop sits here in the sequence")
    is_international_gateway: bool = Field(
        description="Whether this city has its own major international airport access"
    )
    requires_flight_or_ferry: bool = Field(
        description="Carried over from the destination candidate — whether reaching this "
                    "stop from the previous one requires flight/ferry rather than ground transport"
    )

class OrderedItinerary(BaseModel):
    ordered_destinations: list[OrderedStop]
    rationale: str

    @model_validator(mode="before")
    @classmethod
    def unwrap_self_nested_payload(cls, data):
        if isinstance(data, dict) and isinstance(data.get("ordered_destinations"), str):
            try:
                parsed = json.loads(data["ordered_destinations"])
                if isinstance(parsed, dict) and "ordered_destinations" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return data

def order_destinations(state: DestinationResearchState):
    structured_llm = llm.with_structured_output(OrderedItinerary)
    feedback = state.get("order_feedback")
    feedback_block = f"\nTraveler feedback on the previous ordering: {feedback}" if feedback else ""
    expected = state["finalized_destinations"]

    response = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=ordering_instructions),
        HumanMessage(
            content=f"Destinations ({len(expected)} total — every one of these must appear "
                    f"exactly once in your output, none dropped): {expected}\n"
                    f"Preferences: {state['trip_preferences']}{feedback_block}"
        ),
    ], OrderedItinerary)

    stops = [stops.model_dump() for stops in response.ordered_destinations]

    # loosened: gateway city may legitimately appear twice (arrival + dedicated stay),
    # so allow more stops than expected, but never fewer (that means something got dropped)
    if len(stops) < len(expected):
        raise ValueError(
            f"order_destinations dropped destinations: expected at least {len(expected)}, got {len(stops)}"
        )

    if not stops[0]["is_international_gateway"]:
        raise ValueError(
            f"order_destinations didn't start at an international gateway city (started at "
            f"{stops[0]['city']}) — the arrival leg must be represented as the first stop, retry"
        )
    if not stops[-1]["is_international_gateway"]:
        raise ValueError(
            f"order_destinations ended the trip at {stops[-1]['city']}, which isn't flagged "
            f"as having international airport access — retry with better gateway placement"
        )
    return {"ordered_destinations": stops}

def route_after_destination_review(state: DestinationResearchState):
    return "order_destinations" if state.get("review_decision") == "finalize" else "create_analysts"

def review_order(state: DestinationResearchState):
    stops = state["ordered_destinations"]
    raw = interrupt({
        "type": "order_review",
        "message": "Reply 'approve' to finalize, 'drop: <city, city>' to remove optional legs "
                   "(e.g. 'drop: Busan, Jeju'), or describe other changes.",
        "ordered_destinations": stops,
    })

    response = parse_order_response(raw, stops) if isinstance(raw, str) else raw

    if response["type"] == "finalize":
        return {"order_decision": "finalize"}
    elif response["type"] == "drop":
        remaining = [s for i, s in enumerate(stops) if i not in response["drop_indices"]]
        return {"ordered_destinations": remaining, "order_decision": "finalize"}
    else:
        return {"order_feedback": response["feedback"], "order_decision": "revise"}

def route_after_order_review(state: DestinationResearchState):
    return "request_start_date" if state.get("order_decision") == "finalize" else "order_destinations"

def request_start_date(state: DestinationResearchState):
    while True:
        raw = interrupt({
            "type": "start_date_request",
            "message": "Earliest departure date and latest return/must-leave date, "
                       "both required (YYYY-MM-DD, YYYY-MM-DD):",
            "ordered_destinations": state["ordered_destinations"],
        })
        start, _, end = (raw.partition(",") if isinstance(raw, str)
                         else (raw.get("start_date", ""), None, raw.get("end_date", "")))
        start, end = start.strip(), end.strip()
        if start and end:
            return {"trip_start_date": start, "trip_end_date": end}
        # loop repeats, interrupt fires again with the same message

dating_instructions = """Given this ordered itinerary, a trip start date, and a hard end date
(the traveler must be out of the country by this date), assign concrete depart/return dates to
each stop. Pick a duration within each stop's recommended range that respects any stated season
constraints. Stops are sequential and back-to-back unless a stop's purpose implies buffer days
are needed. The final stop's return_date must not exceed the trip end date — if the recommended
durations don't fit within the available window, compress toward the minimum of each stop's
range (dropping buffer days first) rather than exceeding the end date.

If the first stop is a pure arrival/transit stop at the international gateway (distinct from a
later dedicated stay at the same city), give it a short duration (0-1 days) reflecting travel
onward the same or next day, rather than treating it as a full destination stay.

Carry forward each stop's requires_flight_or_ferry value unchanged from the input data — do not
recompute or guess it, just preserve what was given.
"""

def compute_dates(state: DestinationResearchState):
    structured_llm = llm.with_structured_output(DatedItinerary)
    feedback = state.get("date_feedback")
    feedback_block = f"\nTraveler feedback on previous dates: {feedback}" if feedback else ""
    end_date = state.get("trip_end_date")
    end_date_block = f"\nHard end date (must be out of country by): {end_date}" if end_date else ""

    result = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=dating_instructions),
        HumanMessage(content=f"Trip start date: {state['trip_start_date']}{end_date_block}\n"
                              f"Itinerary: {state['ordered_destinations']}{feedback_block}"),
    ], DatedItinerary)

    stops = [s.model_dump() for s in result.stops]

    # hard check — don't rely on the model honoring the constraint unverified
    if end_date and stops:
        last_return = date.fromisoformat(stops[-1]["return_date"])
        if last_return > date.fromisoformat(end_date):
            raise ValueError(
                f"compute_dates exceeded the trip end date: last return {last_return} "
                f"is after deadline {end_date}"
            )

    return {"dated_itinerary": stops}

def review_dates(state: DestinationResearchState):
    raw = interrupt({
        "type": "date_review",
        "message": "Reply 'approve' or describe date changes.",
        "dated_itinerary": state["dated_itinerary"],
    })
    text = raw.strip() if isinstance(raw, str) else None
    if text is not None and text.lower() in APPROVE_SIGNALS:
        return {"date_decision": "finalize"}
    feedback = text if text is not None else raw.get("feedback", "")
    return {"date_feedback": feedback, "date_decision": "revise"}

def route_after_date_review(state: DestinationResearchState):
    return "END" if state.get("date_decision") == "finalize" else "compute_dates"

def _match_ordered_stops(token: str, stops: list) -> list[int]:
    token = token.strip()
    if not token:
        return []
    if token.isdigit():
        idx = int(token)
        return [idx] if 0 <= idx < len(stops) else []
    return [i for i, s in enumerate(stops) if token.lower() in s["city"].lower()]

def parse_order_response(raw: str, stops: list) -> dict:
    text = (raw or "").strip()

    if text.lower() in APPROVE_SIGNALS:
        return {"type": "finalize"}

    if text.lower().startswith(("drop:", "remove:")):
        _, _, rest = text.partition(":")
        dropped: set[int] = set()
        for tok in rest.split(","):
            hits = _match_ordered_stops(tok, stops)
            if not hits:
                return {"type": "revise", "feedback": f"Couldn't match '{tok.strip()}' to drop"}
            dropped.update(hits)
        return {"type": "drop", "drop_indices": dropped}

    return {"type": "revise", "feedback": text}



builder = StateGraph(DestinationResearchState)
builder.add_node("create_analysts", create_analysts)
builder.add_node("human_feedback", human_feedback)
builder.add_node("conduct_interview", interview_builder.compile())
builder.add_node("extract_candidates", extract_candidates)
builder.add_node("review_destinations", review_destinations)
builder.add_node("order_destinations", order_destinations)
builder.add_node("review_order", review_order)
builder.add_node("request_start_date", request_start_date)
builder.add_node("compute_dates", compute_dates)
builder.add_node("review_dates", review_dates)

builder.add_edge(START, "create_analysts")
builder.add_edge("create_analysts", "human_feedback")
builder.add_conditional_edges(
    "human_feedback", initiate_all_interviews,
    ["create_analysts", "conduct_interview"],
)
builder.add_edge("conduct_interview", "extract_candidates")
builder.add_edge("extract_candidates", "review_destinations")
builder.add_conditional_edges(
    "review_destinations", route_after_destination_review,
    ["order_destinations", "create_analysts"],
)
builder.add_edge("order_destinations", "review_order")
builder.add_conditional_edges(
    "review_order", route_after_order_review,
    ["request_start_date", "order_destinations"],
)
builder.add_edge("request_start_date", "compute_dates")
builder.add_edge("compute_dates", "review_dates")
builder.add_conditional_edges(
    "review_dates", route_after_date_review,
    {"END": END, "compute_dates": "compute_dates"},
)

destination_graph = builder.compile(interrupt_before=["human_feedback"])

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "1"}}
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    result = graph.invoke({
        "trip_preferences": input("""
    Please tell about what kind of traveler you are and what you are looking/planning for in this trip:
        1. Budget/General Traveling Preferences
        2. Any tentative dates/months + weather preferences
        3. Any bucket list locations / inspirations you already have in mind
        4. How many people are on this trip
        5. Activities and foods that you enjoy 
        6. Any other preferences you have while traveling, tell us the story of what you would like it to be
    """),
        "max_analysts": 5,
        "analysts": [],
        "sections": [],
        "destination_candidates": [],
        "finalized_destinations": [],
    }, config=config)

    while "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        interrupt_type = interrupt_data["type"]

        if interrupt_type == "human_feedback":
            # this is the original analyst-approval interrupt, still in the graph via interrupt_before
            print("Proposed analyst panel:")
            for a in interrupt_data.get("analysts", []):
                print(f"  - {a}")
            approve = input("Approve this panel? (y = approve, anything else = revise): ")
            resume_value = approve  # let the graph decide what counts as approval
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
            resume_value = input("Earliest available departure date (YYYY-MM-DD): ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        elif interrupt_type == "date_review":
            print("Proposed dates:")
            for s in interrupt_data["dated_itinerary"]:
                print(f"  {s['city']}: {s['depart_date']} → {s['return_date']} ({s['duration_days']}d)")
            resume_value = input("Approve dates (blank/approve), or describe changes: ")
            result = graph.invoke(Command(resume=resume_value), config=config)

        else:
            raise ValueError(f"Unhandled interrupt type: {interrupt_type}")

    print(result["finalized_destinations"])
else:
    graph = builder.compile()