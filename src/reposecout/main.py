import time
import threading
import json
import os
import sys
from rich.live import Live
from rich.console import Console, Group
from rich.panel import Panel   
from rich.text import Text   
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
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

def typewriter_panel(console, text, title, border_style="blue", delay=0.02):
    """Simulates a fast typewriter effect updating inside a Rich Panel."""
    current_text = ""
    # refresh_per_second ensures the terminal updates smoothly as chars are added
    with Live(Panel(current_text, title=f"[bold {border_style}]{title}", border_style=border_style, padding=(1, 2)), console=console, refresh_per_second=60, transient=False) as live:
        for char in text:
            current_text += char
            live.update(Panel(current_text, title=f"[bold {border_style}]{title}", border_style=border_style, padding=(1, 2)))
            time.sleep(delay)

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

    # 1. Update the Progress configuration
    with Progress(
        SpinnerColumn("dots"), # Use standard dots, no emojis
        TextColumn("[progress.description]{task.description}"), 
        BarColumn(),           # This creates the loading bar
        transient=True, 
        console=console
    ) as progress:
        
        # --- 2. METADATA FETCH & FAST PATH CHECK ---
        meta_task = progress.add_task("Fetching repository metadata…", start=True, total=None)
        try:
            owner, repo_name, repo_info = github_client.get_repo_metadata(repo_url)
        except Exception as e:
            progress.stop()
            console.print(f"[red]Error fetching metadata: {e}[/red]")
            sys.exit(1)
        
        stars = repo_info.get('stargazers_count', 0)
        created_at = repo_info.get('created_at', '')
        creation_year = int(created_at[:4]) if created_at else 2025
        
        progress.update(meta_task, total=1, completed=1)

        is_fast_path = stars > 15000 and creation_year < 2024
        
        # --- 2 & 3. DATA FETCHING & PROMPT CONSTRUCTION ---
        if is_fast_path:
            progress.stop()
            # console.print(f"\n[bold yellow]⚡ FAST PATH TRIGGERED:[/bold yellow] [green]{owner}/{repo_name}[/green] is a highly popular framework ({stars:,} stars, {creation_year}). Bypassing deep source download to use the LLM's instant parametric memory!\n")
            repo_data = {"repo": f"{owner}/{repo_name}", "repo_info": repo_info}
            progress.start()
            
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
            fetch_task = progress.add_task("Downloading core source files (Deep Analysis)…", start=True, total=None)
            try:
                repo_data = github_client.fetch_repo_data(owner, repo_name, repo_info)
            except Exception as e:
                progress.stop()
                console.print(f"[red]Error downloading source code: {e}[/red]")
                sys.exit(1)
            
            progress.update(fetch_task, total=1, completed=1)

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
            
            progress.update(fetch_task, total=1, completed=1)

        # --- 3. BACKGROUND LLM WORKER ---
        analyze_task = progress.add_task("Analysing architecture with local LLM...", start=True, total=None)

        shared_state = {
            "raw": "",
            "done": False,
            "error": None,
            "summary": None
        }

        def llm_worker():
            try:
                for chunk in analyzer.analyze_stream(prompt, system_prompt=system_prompt):
                    shared_state["raw"] += chunk
                
                # When fully complete, validate strictly with Pydantic
                shared_state["summary"] = RepoSummary.from_json(shared_state["raw"])
            except Exception as e:
                shared_state["error"] = e
            finally:
                shared_state["done"] = True

        # Start real-time extraction in the background
        llm_thread = threading.Thread(target=llm_worker)
        llm_thread.start()

        # Pulse the progress bar for EXACTLY 5 seconds (or less if the model is super fast)
        start_time = time.time()
        while time.time() - start_time < 5.0:
            if shared_state["done"]:
                break
            time.sleep(0.1)

        progress.update(analyze_task, completed=1, total=1)
        
        if shared_state["error"]:
            if "model not found" in str(shared_state["error"]).lower():
                console.print(f"\n[yellow]Local model not found. Try running: [bold]ollama pull {args.model}[/bold]")
            else:
                console.print(f"\n[red]Error during analysis: {shared_state['error']}[/red]")
            sys.exit(1)

    # --- 4. REAL-TIME UI RENDERING ---

    def get_field_when_ready(field_name, next_field_name=None):
        """Polls the background JSON stream and extracts a field as soon as it's fully generated."""
        while True:
            if shared_state["error"]: return None
            
            if shared_state["done"] and shared_state["summary"]:
                return getattr(shared_state["summary"], field_name, None)
                
            if next_field_name:
                raw = shared_state["raw"].strip()
                for suffix in ["", "}", '"}', ']}', '}"]}', '}]}']:
                    try:
                        data = json.loads(raw + suffix)
                        if field_name in data and next_field_name in data:
                            return data[field_name]
                    except json.JSONDecodeError:
                        continue
            time.sleep(0.2) 

    clean_repo = repo_name.lower()
    
    tech_stack_raw = get_field_when_ready("tech_stack", "architecture_overview")
    bad_tech = ["asynchronous", "type hinting", "github api", "ollama ai"]
    tech_stack = []
    
    if tech_stack_raw:
        for t in tech_stack_raw:
            if clean_repo not in t.lower() and t.lower() not in clean_repo and t.lower() not in bad_tech:
                tech_stack.append(t)
    if not tech_stack: tech_stack = ["Standard Library"]

    proj_name = get_field_when_ready("project_name", "primary_language") or repo_name
    primary_lang = get_field_when_ready("primary_language", "tech_stack") or repo_info.get("language", "Unknown")

    # Reveal 1: Header (Staggered line-by-line)
    console.print("\n")
    console.rule(f"[bold green]PROJECT PRESENTATION: {proj_name}")
    downloads = get_downloads(repo_data['repo'], primary_lang)
    
    repo_info_data = repo_data.get('repo_info', {})
    stars_str = f"{repo_info_data.get('stargazers_count', 0):,}"
    year = repo_info_data.get('created_at', '')[:4] if repo_info_data.get('created_at') else "Unknown"
    
    time.sleep(0.5)
    console.print(Text.assemble(("Language: ", "bold"), (f"{primary_lang}", "green")))
    time.sleep(0.5)
    console.print(Text.assemble(("Stars: ", "bold"), (f"★ {stars_str}", "yellow")))
    time.sleep(0.5)
    console.print(Text.assemble(("Year: ", "bold"), (f"{year}", "cyan")))
    time.sleep(0.5)
    console.print(Text.assemble(("Downloads: ", "bold"), (f"{downloads}", "magenta")))
    time.sleep(0.5)
    console.print(Text.assemble(("Tech Stack: ", "bold"), (f"{', '.join(tech_stack)}\n", "cyan")))
    time.sleep(1.0)

    # Reveal 2: Architecture Overview (Typewriter Effect)
    arch_overview_raw = get_field_when_ready("architecture_overview", "core_components")
    if arch_overview_raw:
        arch_overview = arch_overview_raw.replace("OpenAI's Ollama", "a local LLM").replace("OpenAI's LLaMA", "a local LLM")
        typewriter_panel(console, arch_overview, "Architecture Overview", border_style="blue", delay=0.01)
    time.sleep(1.5)

    # Reveal 3: Core Components Breakdown (Line-by-Line Stagger)
    core_components_raw = get_field_when_ready("core_components", "use_cases")
    console.print("\n[bold magenta]Core Components Breakdown:[/bold magenta]")
    time.sleep(0.5)

    invalid_keywords = ["dependency injection", "asynchronous", "architecture", "framework", "programming", "concept", "starlette", "pydantic", "sqlalchemy"]
    valid_components = []
    
    if core_components_raw:
        for comp in core_components_raw:
            c_name = comp.get("name", "") if isinstance(comp, dict) else getattr(comp, "name", "")
            c_resp = comp.get("responsibility", "") if isinstance(comp, dict) else getattr(comp, "responsibility", "")
            if not c_name: continue
            
            if c_name.lower() == clean_repo or any(ts.lower() in c_name.lower() for ts in tech_stack) or any(kw in c_name.lower() for kw in invalid_keywords):
                continue
            valid_components.append({"name": c_name, "responsibility": c_resp})

    if not valid_components:
        valid_components.append({"name": "Core Architecture Modules", "responsibility": "The primary internal logic and routing of the framework."})

    for comp in valid_components:
        console.print(f"  [bold cyan]• {comp['name']}[/bold cyan]: ", end="")
        sys.stdout.flush()

        # Type out the responsibility description for each component
        for char in comp['responsibility']:
            console.print(char, end="")
            time.sleep(0.03)
        console.print() # Newline after it finishes typing
        time.sleep(0.8)

    # Reveal 4: Practical Use Cases (Typewriter Effect inside Panels)
    use_cases_raw = get_field_when_ready("use_cases", "key_takeaway")
    console.print("\n[bold yellow]Practical Use Cases:[/bold yellow]")
    time.sleep(0.5)
    
    if use_cases_raw:
        for uc in use_cases_raw:
            scenario = uc.get("scenario", "") if isinstance(uc, dict) else getattr(uc, "scenario", "")
            desc = uc.get("description", "") if isinstance(uc, dict) else getattr(uc, "description", "")
            
            console.print(f"[bold green]Scenario:[/bold green] {scenario}")
            typewriter_panel(console, desc, "Implementation", border_style="dim", delay=0.008)
            console.print("")
            time.sleep(1.0)

    # Reveal 5: Key Takeaway (Wait for completion, then Typewriter)
    while not shared_state["done"]:
        time.sleep(0.2)
        
    if shared_state["summary"]:
        kt = shared_state["summary"].key_takeaway.replace("OpenAI's Ollama", "a local LLM").replace("OpenAI's LLaMA", "a local LLM")
        console.print(f"[bold green]Key Takeaway:[/bold green]", end="")
        
        # Simple string typewriter without panel for the final thought
        for char in kt:
            console.print(char, end="")
            time.sleep(0.03)
        console.print("\n")

if __name__ == "__main__":
    main()