import os
import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from reposecout.github_client import GitHubScout
from reposecout.analyzer import LocalAnalyzer
from reposecout.models import RepoSummary

MODEL_NAME = os.getenv("MODEL_NAME")
def build_source_section(core_source_files: dict) -> str:
    """Format fetched source files into a prompt section."""
    if not core_source_files:
        return "(no source files could be fetched)\n"
    parts = []
    for path, content in core_source_files.items():
        parts.append(f"--- {path} ---\n{content}\n")
    return "\n".join(parts)

def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="RepoScout: Summarize a GitHub repository.")
    parser.add_argument("repo_url", type=str, help="GitHub repository URL")
    parser.add_argument("--model", type=str, default=MODEL_NAME, help="Ollama model to use (default: qwen2.5-coder:7b)")
    parser.add_argument("--core-files", type=int, default=10, help="Number of core source files to fetch (default: 10)")
    args = parser.parse_args()
    console = Console()

    repo_url = args.repo_url
    if not repo_url.startswith("http://") and not repo_url.startswith("https://"):
        repo_url = "https://" + repo_url

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print("[red]Error: GITHUB_TOKEN environment variable not set. Please set it to access the GitHub API.")
        sys.exit(1)

    github_client = GitHubScout(token)
    analyzer = LocalAnalyzer(model=args.model)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True, console=console) as progress:
        fetch_task = progress.add_task("Fetching repository data…", start=True)
        try:
            repo_data = github_client.fetch_repo_data(repo_url)
        except Exception as e:
            progress.stop()
            console.print(f"[red]Error: {e}")
            sys.exit(1)
        progress.update(fetch_task, completed=1)

        n_core = len(repo_data.get('core_source_files', {}))
        analyze_task = progress.add_task(
            f"Analysing architecture ({n_core} source files) with local LLM…", start=True
        )

        kfc = repo_data['key_files_content']
        core_source_section = build_source_section(repo_data.get('core_source_files', {}))
        prompt = (
            f"ACTING AS A TECHNICAL ADVOCATE FOR: {repo_data['repo']}\n\n"
            "Your goal is to provide a deep-dive technical presentation for a senior developer. "
            "Do not provide generic overviews. Analyze the provided source code to find unique implementation details.\n\n"
            
            "REQUIREMENTS:\n"
            "1. PROJECT DESCRIPTION: Provide a multi-paragraph technical deep-dive. "
            "Explain HOW the architecture handles its primary responsibility (e.g., mention specific base classes, "
            "decorators, or data-flow logic found in the core files). Describe the 'Internal Philosophy' of the code.\n"
            
            "2. TECH STACK: List only the core runtime and essential production dependencies. "
            "Briefly explain WHY a specific dependency is central to this project's architecture.\n"
            
            "3. USE CASES: Provide 3-5 specific, complex scenarios. For each, explain exactly which part of this "
            "codebase enables that use case (e.g., 'The async middleware in routing.py makes this ideal for X').\n"
            
            "4. NO EXTENSION DATA: Focus strictly on USAGE. Ignore internal testing, contribution guides, or dev-ops scripts.\n\n"

            "STRICT RULES FOR THE LLM:\n"
            "- Use 'Senior-to-Senior' technical language.\n"
            "- If you mention a feature, back it up with evidence from the 'KEY SOURCE FILES' below.\n"
            "- Avoid marketing fluff like 'easy-to-use' or 'seamless'. Use 'declarative' or 'low-overhead' instead.\n\n"

            "=== DIRECTORY STRUCTURE ===\n"
            f"{chr(10).join(repo_data['summarized_tree'])}\n\n"
            
            "=== KEY SOURCE FILES (Primary Evidence) ===\n"
            f"{core_source_section}"
        )
        try:
            summary = analyzer.analyze(prompt)
        except Exception as e:
            progress.stop()
            if "model not found" in str(e).lower():
                console.print(f"[yellow]Local model not found. Try running: [bold]ollama pull {args.model}[/bold]")
            else:
                console.print(f"[red]Error during analysis: {e}")
            sys.exit(1)
        progress.update(analyze_task, completed=1)

    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group

    # Header and Basic Metadata
    console.rule(f"[bold green]PROJECT PRESENTATION: {summary.project_name}")
    
    metadata = Text.assemble(
        ("\nLanguage: ", "bold"), (f"{summary.primary_language}", "green"),
        ("\nTech Stack: ", "bold"), (f"{', '.join(summary.tech_stack)}\n", "cyan")
    )
    console.print(metadata)

    # Detailed Project Description (Informative Section)
    console.print(Panel(
        summary.project_description,
        title="[bold blue]Technical Overview",
        border_style="blue",
        padding=(1, 2)
    ))

    # Use Cases (Structured Scenarios)
    console.print("\n[bold yellow]Target Use Cases & Scenarios:[/bold yellow]")
    
    for uc in summary.use_cases:
        use_case_group = Group(
            Text(f"Scenario: {uc.scenario}", style="bold green"),
            Text(f"{uc.description}", style="white")
        )
        console.print(Panel(use_case_group, border_style="dim"))
        console.print("")


if __name__ == "__main__":
    main()
