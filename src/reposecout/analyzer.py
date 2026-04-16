import os
from ollama import chat
from reposecout.models import RepoSummary

class LocalAnalyzer:
    def __init__(self, model: str = None):
        if model is None:
            model = os.getenv("MODEL_NAME")
        self.model = model

    def analyze_stream(self, prompt: str, system_prompt: str = None):
        if not system_prompt:
            system_prompt = (
                "You are an expert Software Architect and Technical Educator. "
                "Analyze the provided repository and explain its architecture in a structured manner. "
                "Focus on tangible facts, data flow, component responsibilities, and structural patterns."
            )

        # We set stream=True to get chunks of data live
        response = chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            format=RepoSummary.model_json_schema(),
            options={"temperature": 0.2},
            stream=True 
        )
        
        # Yield each piece of text as the LLM thinks of it
        for chunk in response:
            yield chunk["message"]["content"]