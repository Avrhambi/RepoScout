import os
import requests
from urllib.parse import urlparse
import re
import concurrent.futures 

class GitHubScout:
    MEANINGFUL_EXTS = (
            '.py', '.js', '.ts', '.go', '.rs', '.java', '.c', '.cpp', '.cs', '.rb', '.php', '.swift', '.kt', '.scala', '.m', '.dart', '.sh', '.pl', '.lua', '.r', '.jl', '.hs', '.fs', '.tsx', '.jsx'
        )
    
    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHub token must be provided.")
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}"
        }
        self.image_exts = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico')
        self.lock_patterns = re.compile(r"(\\.lock$|package-lock\\.json$|yarn.lock$|poetry.lock$)")

    def search_repo_by_name(self, repo_name: str) -> tuple[str, str, str]:
        """
        Uses GitHub's Search API to find the most popular repository matching the name.
        Returns (html_url, owner, repo_name) or (None, None, None).
        """
        url = f"https://api.github.com/search/repositories?q={repo_name}+in:name&sort=stars&order=desc"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if items:
                # Return the most starred repository that matches the search
                top_repo = items[0]
                return top_repo["html_url"], top_repo["owner"]["login"], top_repo["name"]
        return None, None, None

    def summarize_tree(self, tree):
        """
        Only include files with meaningful extensions.
        No longer collapses folders — returns the full flat list so the LLM
        can see the real module structure.
        """
        summarized = []
        for item in tree:
            path = item.get('path', '')
            if item.get('type') != 'blob':
                continue
            if not path.lower().endswith(self.MEANINGFUL_EXTS):
                continue
            summarized.append(path)
        return summarized
    
    def score_file(self, path: str) -> int:
        """
        Heuristic score for how architecturally interesting a source file is.
        Higher = more likely to reveal internal mechanics worth sending to the LLM.
        """
        score = 0
        name = path.split('/')[-1].lower()
        parts = path.lower().split('/')

        # Penalise test / docs / examples / migrations
        skip_dirs = {'test', 'tests', 'spec', 'specs', 'docs', 'doc',
                     'examples', 'example', 'migrations', 'fixtures',
                     'vendor', 'node_modules', '__pycache__', 'dist', 'build'}
        if any(p in skip_dirs for p in parts):
            return -1

        # Reward names that are almost always core logic
        core_names = {
            'app', 'main', 'server', 'router', 'routing', 'index','base','interface','models','schema',
            'core', 'base', 'engine', 'pipeline', 'handler', 'middleware',
            'dispatcher', 'scheduler', 'worker', 'manager', 'controller',
            'application', 'cli', 'run', 'entry', 'bootstrap',
        }
        stem = name.rsplit('.', 1)[0]
        if stem in core_names:
            score += 10

        # Reward common entry-point patterns
        if name in ('__init__.py', 'index.ts', 'index.js', 'main.go',
                    'lib.rs', 'mod.rs', 'main.rs'):
            score += 6

        # Reward shallow depth (top-level package files are usually important)
        depth = len(parts) - 1  # number of directory levels
        score += max(0, 5 - depth)

        # Prefer Python / Go / Rust (usually richer logic per file than JS/TS)
        if name.endswith(('.py', '.go', '.rs')):
            score += 2

        return score

    def pick_core_files(self, tree, max_files: int = 10) -> list[str]:
        """
        Return the paths of the most architecturally interesting source files,
        scored by `score_file`. Skips files whose score is negative.
        """
        candidates = []
        for item in tree:
            if item.get('type') != 'blob':
                continue
            path = item['path']
            if not path.lower().endswith(self.MEANINGFUL_EXTS):
                continue
            s = self.score_file(path)
            if s >= 0:
                candidates.append((s, path))

        candidates.sort(key=lambda x: -x[0])
        return [path for _, path in candidates[:max_files]]

    def fetch_core_source_files(self, owner: str, repo: str, tree: list,
                                max_files: int = 10, max_chars_per_file: int = 3000) -> dict[str, str]:
        """
        Fetch the content of the most important source files CONCURRENTLY.
        """
        paths = self.pick_core_files(tree, max_files=max_files)
        result = {}

        # Helper function for the thread pool
        def fetch_single_file(path):
            content = self.fetch_file_content(owner, repo, path)
            if content:
                return path, content[:max_chars_per_file]
            return path, None

        # Execute all 10 downloads at the exact same time
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_path = {executor.submit(fetch_single_file, path): path for path in paths}
            for future in concurrent.futures.as_completed(future_to_path):
                try:
                    path, content = future.result()
                    if content:
                        result[path] = content
                except Exception as e:
                    pass # Silently skip files that fail to download

        return result

    def get_github_repo_info(self, repo_url):
        parsed = urlparse(repo_url)
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "github.com":
            return None, None
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) < 2:
            return None, None
        return path_parts[0], path_parts[1]

    def get_repo_metadata(self, repo_url):
        """Fetches just the repository metadata to check stars and creation year."""
        owner, repo = self.get_github_repo_info(repo_url)
        if not owner or not repo:
            raise ValueError(f"Invalid GitHub repository URL '{repo_url}'.")
        repo_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=self.headers)
        repo_resp.raise_for_status()
        return owner, repo, repo_resp.json()

    def fetch_github_file_tree(self, owner, repo, repo_info):
        """Fetches the tree using the already retrieved repo_info."""
        branch = repo_info.get("default_branch", "main")
        branch_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1", headers=self.headers)
        branch_resp.raise_for_status()
        return branch_resp.json()["tree"] 

    def filter_tree(self, tree):
        filtered = []
        for item in tree:
            path = item.get('path', '')
            if path.startswith('.git'):
                continue
            if path.lower().endswith(self.image_exts):
                continue
            if self.lock_patterns.search(path):
                continue
            filtered.append(item)
        return filtered

    def fetch_file_content(self, owner, repo, path):
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('encoding') == 'base64':
                import base64
                return base64.b64decode(data['content']).decode('utf-8', errors='replace')
            return data.get('content', '')
        return None

    def extract_key_files(self, owner, repo, tree):
        key_files = ['README.md', 'package.json', 'requirements.txt', 'pyproject.toml']
        found = {k: None for k in key_files}
        for item in tree:
            path = item.get('path', '')
            for k in key_files:
                if path.lower() == k.lower() and item.get('type') == 'blob':
                    found[k] = self.fetch_file_content(owner, repo, path)
        return found

    def fetch_repo_data(self, owner, repo, repo_info):
        """Performs the deep fetch of the tree and core source files."""
        tree = self.fetch_github_file_tree(owner, repo, repo_info)
        filtered_tree = self.filter_tree(tree)
        summarized_tree = self.summarize_tree(filtered_tree)
        key_files_content = self.extract_key_files(owner, repo, filtered_tree)
        core_source_files = self.fetch_core_source_files(owner, repo, filtered_tree)
        return {
            "owner": owner,
            "repo": repo,
            "repo_info": repo_info,
            "tree": tree,
            "filtered_tree": filtered_tree,
            "summarized_tree": summarized_tree,
            "key_files_content": key_files_content,
            "core_source_files": core_source_files,
        }

