from pydantic import BaseModel, Field
from typing import List

class UseCase(BaseModel):
    scenario: str = Field(description="A specific, technical scenario (e.g., 'Real-time Data Streaming').")
    description: str = Field(description="A detailed explanation of how this project solves problems in this specific scenario.")

class RepoSummary(BaseModel):
    project_name: str
    primary_language: str
    tech_stack: List[str] = Field(
        description="List of core libraries and frameworks. Exclude dev-dependencies like 'pytest' or 'black'."
    )
    project_description: str = Field(
        description="A deep-dive technical overview. Explain the 'What' and the 'Why'. Aim for 2-3 substantial paragraphs."
    )
    use_cases: List[UseCase] = Field(
        description="3-5 detailed scenarios where a developer would choose to use this project over alternatives."
    )

    @classmethod
    def from_json(cls, data: str) -> "RepoSummary":
        import json
        return cls.model_validate_json(data)
