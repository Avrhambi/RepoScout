from ollama import chat
from reposecout.models import RepoSummary

class LocalAnalyzer:
    def __init__(self, model: str = "qwen2.5-coder:7b"):
        self.model = model

    def analyze(self, prompt: str) -> RepoSummary:
        # The System Message is the "anchor" for 7b models
        system_content = (
            "You are a Technical Product Architect. Your goal is to pitch this repository to other developers. "
            "Be descriptive and highly technical. Avoid vague marketing fluff. "
            "When describing the project or use cases, provide depth—explain the technical 'how' behind the 'what'. "
            "Use only the provided source code and file tree to inform your answers."
        )

        response = chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ],
            format=RepoSummary.model_json_schema(),
            options={"temperature": 0.2} # Slightly higher temp (0.2) allows for more descriptive prose
        )
        return RepoSummary.from_json(response["message"]["content"])

