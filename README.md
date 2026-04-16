# RepoScout: Local AI Repository Analyzer

RepoScout is a local tool for analyzing GitHub repositories using AI models. It leverages Ollama and a local LLM to provide insights into any codebase.

## Setup

1. Clone the project:

   ```bash
   git clone https://github.com/Avrhambi/RepoScout
   ```
   ```bash
   cd RepoScout
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   ```
   ```bash
   # On Windows:
   venv\Scripts\activate
   ```
   ```bash
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
4. Create a GitHub token in here: https://github.com/settings/tokens

5. Chnage `env.exanple` to `.env` and place the GitHub token.

## How to Run

Run RepoScout as a Python module, providing the GitHub repository URL:

```bash
python -m reposecout.main <URL>
```

Replace `<URL>` with the GitHub repository you want to analyze (e.g., `https://github.com/tiangolo/fastapi`).

## Note

- RepoScout requires [Ollama](https://ollama.com/) to be running locally.
- For bettter results, use at least a 7B parameters model with Ollama.
