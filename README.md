# RepoScout: Local AI Repository Analyzer

RepoScout is a local tool for analyzing GitHub repositories using AI models. It leverages Ollama and a local LLM to provide insights into any codebase.

## Setup

1. Clone the project:

   ```bash
   git clone https://github.com/Avrhambi/RepoScout
   cd RepoScout
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root with your GitHub token:

   ```env
   GITHUB_TOKEN=your_github_token_here
   ```

## How to Run

Run RepoScout as a Python module, providing the GitHub repository URL:

```bash
python -m reposecout.main <URL>
```

Replace `<URL>` with the GitHub repository you want to analyze (e.g., `https://github.com/tiangolo/fastapi`).

## Note

- RepoScout requires [Ollama](https://ollama.com/) to be running locally.
- For bettter results, use at least a 7B parameters model with Ollama.
