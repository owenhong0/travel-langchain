import operator
import time
from typing import TypedDict, Optional, List, Annotated

from anthropic import APIStatusError
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, get_buffer_string, AIMessage
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph, MessagesState
from langgraph.types import Send, interrupt, Command
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

llm = ChatAnthropic(model_name="claude-sonnet-5", thinking={"type": "disabled"})  # used for .with_structured_output(...) calls
retryable_llm = llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)

def invoke_structured_with_retry(structured_llm, messages, schema, attempts=3):
    last_error = None
    for i in range(attempts):
        try:
            return structured_llm.invoke(messages)
        except ValidationError as e:
            # Known issue: for schemas whose sole field is a list, the model
            # sometimes returns the whole JSON payload as a string instead of
            # a parsed object. Try to recover by parsing it ourselves.
            errors = e.errors()
            if len(errors) == 1 and errors[0]["type"] == "list_type" and isinstance(errors[0]["input"], str):
                try:
                    return schema.model_validate_json(errors[0]["input"])
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

class DestinationCandidate(BaseModel):
    city: str
    country: str
    rationale: str
    recommended_season: str = Field(description="Best time of year to visit, e.g. 'Spring (March-May)' or 'Year-round'")
    recommended_duration_days_min: int
    recommended_duration_days_max: int
    rationale: str = Field(description="Why this fits the traveler's stated preferences")
    date: str = Field(description="What date best fits the traveler's stated preferences")

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
        max_analysts=state.get("max_analysts", 3),
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
def search_gov_travel(state: DestinationInterviewState):
    structured_llm = llm.with_structured_output(SearchQuery)
    messages = [search_instructions] + as_incoming(state["messages"]) + [
        HumanMessage(content="Based on the conversation above, generate a search query.")
    ]
    search_query = invoke_structured_with_retry(structured_llm, messages, SearchQuery)
    tavily_search = TavilySearch(max_results=3, include_domains=GOV_TRAVEL_DOMAINS)
    data = tavily_search.invoke({"query": search_query.search_query, "include_images": True})
    image_urls = data.get("images", [])
    docs = data.get("results", data)
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
    data = tavily_search.invoke({"query": search_query.search_query, "include_images": True})
    image_urls = data.get("images", [])
    docs = data.get("results", data)
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
    data = tavily_search.invoke({"query": search_query.search_query, "include_images": True})
    image_urls = data.get("images", [])
    docs = data.get("results", data)
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
for the same destination, use your judgment to reconcile into a single reasonable range."""

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

APPROVE_SIGNALS = {"approve", "y", "yes", "all", ""}

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
        "type": "destination_review",
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

def route_after_review(state: DestinationResearchState):
    return "END" if state.get("review_decision") == "finalize" else "create_analysts"

builder = StateGraph(DestinationResearchState)
builder.add_node("create_analysts", create_analysts)
builder.add_node("human_feedback", human_feedback)
builder.add_node("conduct_interview", interview_builder.compile())
builder.add_node("extract_candidates", extract_candidates)
builder.add_node("review_destinations", review_destinations)

builder.add_edge(START, "create_analysts")
builder.add_edge("create_analysts", "human_feedback")
builder.add_conditional_edges("human_feedback", initiate_all_interviews, ["create_analysts", "conduct_interview"])
builder.add_edge("conduct_interview", "extract_candidates")
builder.add_edge("extract_candidates", "review_destinations")
builder.add_conditional_edges("review_destinations", route_after_review, {
    "END": END,
    "create_analysts": "create_analysts",
})

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

        else:
            raise ValueError(f"Unhandled interrupt type: {interrupt_type}")

    print(result["finalized_destinations"])
else:
    graph = builder.compile()