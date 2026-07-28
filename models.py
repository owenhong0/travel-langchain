from pydantic import BaseModel

class DestinationSearch(BaseModel):
    Countries: list[str]
    Cities: list[str]
    Sources: list[str]
    Pictures: list[str]
    Reasonings: list[str]