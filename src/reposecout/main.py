import os
import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from reposecout.github_client import GitHubScout
from reposecout.analyzer import LocalAnalyzer
from reposecout.models import RepoSummary, CoreComponent

MODEL_NAME = os.getenv("MODEL_NAME")

def build_source_section(core_source_files: dict) -> str:
    """Format fetched source files into a prompt section."""
    if not core_source_files:
        return "(no source files could be fetched)\n"
    parts = []
    for path, content in core_source_files.items():
        parts.append(f"--- {path} ---\n{content}\n")
    return "\n".join(parts)

def get_downloads(repo_input_string: str, language: str) -> str:
    """Dynamically fetch package downloads based on the primary language."""
    import requests
    # Fix: Extract only the package name (e.g., 'fastapi' from 'tiangolo/fastapi')
    package_name = repo_input_string.split('/')[-1].lower()
    try:
        lang = language.lower()
        if "javascript" in lang or "typescript" in lang or "node" in lang:
            resp = requests.get(f"https://api.npmjs.org/downloads/point/last-month/{package_name}", timeout=3)
            if resp.status_code == 200:
                return f"{resp.json().get('downloads', 0):,} (NPM last month)"
        elif "python" in lang:
            resp = requests.get(f"https://pypistats.org/api/packages/{package_name}/recent", timeout=3)
            if resp.status_code == 200:
                return f"{resp.json().get('data', {}).get('last_month', 0):,} (PyPI last month)"
        elif "rust" in lang:
            resp = requests.get(f"https://crates.io/api/v1/crates/{package_name}", timeout=3)
            if resp.status_code == 200:
                return f"{resp.json().get('crate', {}).get('downloads', 0):,} (Crates.io all-time)"
    except Exception:
        pass
    return "N/A (Package stats unavailable)"


def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="RepoScout: Summarize a GitHub repository.")
    parser.add_argument("repo_url", type=str, help="GitHub repository URL, 'owner/repo', or package name")
    parser.add_argument("--model", type=str, default=MODEL_NAME, help="Ollama model to use")
    parser.add_argument("--core-files", type=int, default=10, help="Number of core source files to fetch")
    args = parser.parse_args()
    console = Console()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print("[red]Error: GITHUB_TOKEN environment variable not set.[/red]")
        sys.exit(1)

    github_client = GitHubScout(token)
    repo_input = args.repo_url

    # --- 1. RESOLVE REPOSITORY NAME TO URL ---
    if "/" not in repo_input:
        # console.print(f"🔍 Searching for popular repository matching '[bold]{repo_input}[/bold]'...")
        search_url, owner, repo_name = github_client.search_repo_by_name(repo_input)
        if not search_url:
            console.print(f"[yellow]Could not quickly find a definitive repository for '{repo_input}'. Please run the tool again with the full GitHub URL.[/yellow]")
            sys.exit(1)
        repo_url = search_url
        # console.print(f"[green]Found repository: {owner}/{repo_name} ({repo_url})[/green]\n")
    else:
        if not repo_input.startswith("http"):
            if "github.com" not in repo_input:
                repo_url = f"https://github.com/{repo_input}"
            else:
                repo_url = f"https://{repo_input}"
        else:
            repo_url = repo_input

    analyzer = LocalAnalyzer(model=args.model)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True, console=console) as progress:
        
        # --- 2. METADATA FETCH & FAST PATH CHECK ---
        meta_task = progress.add_task("Fetching repository metadata…", start=True)
        try:
            owner, repo_name, repo_info = github_client.get_repo_metadata(repo_url)
        except Exception as e:
            progress.stop()
            console.print(f"[red]Error fetching metadata: {e}[/red]")
            sys.exit(1)
        
        stars = repo_info.get('stargazers_count', 0)
        created_at = repo_info.get('created_at', '')
        creation_year = int(created_at[:4]) if created_at else 2025
        
        progress.update(meta_task, completed=1)

        is_fast_path = stars > 15000 and creation_year < 2024
        
        if is_fast_path:
            progress.stop()
            # console.print(f"\n[bold yellow]⚡ FAST PATH TRIGGERED:[/bold yellow] [green]{owner}/{repo_name}[/green] is a highly popular framework ({stars:,} stars, {creation_year}). Bypassing deep source download to use the LLM's instant parametric memory!\n")
            repo_data = {"repo": f"{owner}/{repo_name}", "repo_info": repo_info}
            progress.start()
        else:
            fetch_task = progress.add_task("Downloading core source files (Deep Analysis)…", start=True)
            try:
                repo_data = github_client.fetch_repo_data(owner, repo_name, repo_info)
            except Exception as e:
                progress.stop()
                console.print(f"[red]Error downloading source code: {e}[/red]")
                sys.exit(1)
            progress.update(fetch_task, completed=1)

    # --- 3. LLM PROMPT CONSTRUCTION ---
        analyze_task = progress.add_task("Analysing architecture with local LLM...", start=True)

        if is_fast_path:
            system_prompt = (
                "You are an expert Software Architect. Explain the architecture of this famous repository using your deep pre-trained knowledge. "
                "Be highly specific about its internal modules and source code files. Avoid vague marketing fluff."
            )
            prompt = (
                f"Please provide an architectural deep-dive for: {repo_data['repo']}.\n\n"
                "REQUIREMENTS:\n"
                "1. ARCHITECTURE OVERVIEW: Provide a deep-dive, structured overview of the system's design.\n"
                "2. CORE COMPONENTS: Identify 3-5 of the most critical SOURCE CODE FILES or internal directories. DO NOT list abstract concepts or external dependencies.\n"
                "3. ACCESSIBILITY: Write clearly so developers of all skill levels can learn from it.\n"
            )
        else:
            system_prompt = (
                "You are an expert Software Architect. Analyze the provided repository and explain its architecture. "
                "Use ONLY the provided source code and file tree. Focus on specific source files, tangible facts, and component responsibilities."
            )
            core_source_section = build_source_section(repo_data.get('core_source_files', {}))
            prompt = (
                f"Please analyze the repository: {repo_data['repo']}\n\n"
                "REQUIREMENTS:\n"
                "1. ARCHITECTURE OVERVIEW: Provide a structured overview of the system's design.\n"
                "2. CORE COMPONENTS: Identify the most important SPECIFIC FILES from the source provided. Detail their exact responsibilities.\n"
                "3. STRICT EVIDENCE: Base your analysis *only* on the provided directory structure and source files.\n\n"
                "=== DIRECTORY STRUCTURE ===\n"
                f"{chr(10).join(repo_data.get('summarized_tree', []))}\n\n"
                "=== KEY SOURCE FILES ===\n"
                f"{core_source_section}"
            )

        try:
            raw_json_output = ""
            # Stream the JSON invisibly in the background while the progress spinner turns
            for chunk in analyzer.analyze_stream(prompt, system_prompt=system_prompt):
                raw_json_output += chunk
                
            summary = RepoSummary.from_json(raw_json_output)
            
            # --- 4. POST-PROCESSING & DATA CLEANUP ---
            clean_repo = repo_name.lower()
            
            summary.architecture_overview = summary.architecture_overview.replace("OpenAI's Ollama", "a local LLM").replace("OpenAI's LLaMA", "a local LLM")
            summary.key_takeaway = summary.key_takeaway.replace("OpenAI's Ollama", "a local LLM").replace("OpenAI's LLaMA", "a local LLM")
            
            bad_tech = ["asynchronous", "type hinting", "github api", "ollama ai"]
            summary.tech_stack = [
                tech for tech in summary.tech_stack 
                if clean_repo not in tech.lower() and tech.lower() not in clean_repo and tech.lower() not in bad_tech
            ]
            if not summary.tech_stack:
                summary.tech_stack = ["Standard Library"]

            valid_components = []
            invalid_keywords = ["dependency injection", "asynchronous", "architecture", "framework", "programming", "concept", "starlette", "pydantic", "sqlalchemy"]
            
            for comp in summary.core_components:
                c_name = comp.name.lower()
                if c_name == clean_repo or any(ts.lower() in c_name for ts in summary.tech_stack) or any(kw in c_name for kw in invalid_keywords):
                    continue
                valid_components.append(comp)
                
            summary.core_components = valid_components
            
            if not summary.core_components:
                summary.core_components.append(CoreComponent(
                    name="Core Architecture Modules",
                    responsibility="The primary internal logic and routing of the framework."
                ))

        except Exception as e:
            progress.stop()
            if "model not found" in str(e).lower():
                console.print(f"\n[yellow]Local model not found. Try running: [bold]ollama pull {args.model}[/bold]")
            else:
                console.print(f"\n[red]Error during analysis: {e}[/red]")
            sys.exit(1)
            
        progress.update(analyze_task, completed=1)

    # --- 5. UI RENDERING (Staggered Reveal) ---
    import time
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Group

    repo_info = repo_data.get('repo_info', {})
    stars_str = f"{repo_info.get('stargazers_count', 0):,}"
    created_at = repo_info.get('created_at', '')
    year = created_at[:4] if created_at else "Unknown"
    downloads = get_downloads(repo_data['repo'], summary.primary_language)

    # Reveal 1: Header
    console.print("\n")
    console.rule(f"[bold green]PROJECT PRESENTATION: {summary.project_name}")
    metadata = Text.assemble(
        ("\nLanguage: ", "bold"), (f"{summary.primary_language}", "green"),
        (" | ", "dim"),
        ("Stars: ", "bold"), (f"★ {stars_str}", "yellow"),
        (" | ", "dim"),
        ("Year: ", "bold"), (f"{year}", "cyan"),
        (" | ", "dim"),
        ("Downloads: ", "bold"), (f"{downloads}", "magenta"),
        ("\nTech Stack: ", "bold"), (f"{', '.join(summary.tech_stack)}\n", "cyan")
    )
    console.print(metadata)
    time.sleep(1.5) # Wait to read header

    # Reveal 2: Architecture Overview
    console.print(Panel(
        summary.architecture_overview,
        title="[bold blue]Architecture Overview",
        border_style="blue",
        padding=(1, 2)
    ))
    time.sleep(2.5) # Wait to read overview

    # Reveal 3: Core Components (Staggered)
    console.print("\n[bold magenta]Core Components Breakdown:[/bold magenta]")
    time.sleep(0.5)
    for comp in summary.core_components:
        console.print(f"  [bold cyan]• {comp.name}[/bold cyan]: {comp.responsibility}")
        time.sleep(1.0) # Pause between each component

    # Reveal 4: Use Cases (Staggered)
    console.print("\n[bold yellow]Practical Use Cases:[/bold yellow]")
    time.sleep(0.5)
    for uc in summary.use_cases:
        use_case_group = Group(
            Text(f"Scenario: {uc.scenario}", style="bold green"),
            Text(f"{uc.description}", style="white")
        )
        console.print(Panel(use_case_group, border_style="dim"))
        console.print("")
        time.sleep(1.5) # Pause between each use case

    # Reveal 5: Key Takeaway
    console.print(f"[bold green]Key Takeaway:[/bold green] {summary.key_takeaway}\n")

if __name__ == "__main__":
    main()