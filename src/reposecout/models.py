from pydantic import BaseModel, Field
from typing import List

class CoreComponent(BaseModel):
    name: str = Field(
        description="The exact file path or module name. MUST BE A FILE OR DIRECTORY. Do not list frameworks, dependencies, or concepts."
    )
    responsibility: str = Field(
        description="Explain what this specific file or directory does in the system."
    )

class UseCase(BaseModel):
    scenario: str = Field(
        description="A specific, practical scenario where this tool is highly valuable."
    )
    description: str = Field(
        description="Detailed explanation of how the project's architecture solves problems in this scenario."
    )


class RepoSummary(BaseModel):
    project_name: str
    primary_language: str
    tech_stack: List[str] = Field(
        description="List ONLY specific frameworks and libraries (e.g., React, FastAPI, NumPy). Do not list the project name itself, and do not list abstract concepts like 'Type Hinting' or 'Asynchronous'."
    )
    architecture_overview: str = Field(
        description="Explain the core data flow and system structure. Do not mention the tools used to generate this summary (e.g., do not mention LLMs, Ollama, or OpenAI)."
    )
    core_components: List[CoreComponent] = Field(
        description="Break down the top 2 to 3 most critical internal source code files."
    )
    use_cases: List[UseCase] = Field(
        description="Provide exactly 2 highly specific, practical scenarios where this project excels."
    )
    key_takeaway: str = Field(
        description="One concluding paragraph summarizing the project's main value."
    )

    @classmethod
    def from_json(cls, data: str) -> "RepoSummary":
        import json
        return cls.model_validate_json(data)