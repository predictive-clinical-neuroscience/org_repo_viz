#!/usr/bin/env python3
"""
GitHub Organization Repository Visualizer - Data Fetcher

Usage:
    python fetch.py <org_name>
    python fetch.py <org_name> --token ghp_xxxx
    GITHUB_TOKEN=ghp_xxxx python fetch.py <org_name>
    python fetch.py  # reads GITHUB_ORG and GITHUB_TOKEN from .env

The output is written to docs/data.json by default.
Open docs/index.html locally or push docs/ to GitHub Pages to view the visualization.
"""

import os
import sys
import json
import re
import base64
import argparse
import time
import dotenv
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' library not found. Run: pip install requests")
    sys.exit(1)


class GitHubClient:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.base_url = "https://api.github.com"

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        while True:
            resp = self.session.get(url, params=params)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - time.time(), 0) + 2
                print(f"\n  Rate limited. Waiting {wait:.0f}s...", flush=True)
                time.sleep(wait)
                continue
            if resp.status_code == 202:
                # GitHub is computing stats asynchronously
                time.sleep(3)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code == 409:
                # Empty repo
                return None
            resp.raise_for_status()
            return resp

    def get_json(self, path, params=None):
        resp = self.get(path, params=params)
        return resp.json() if resp else None

    def get_all_pages(self, path, params=None, max_pages=20):
        params = {**(params or {}), "per_page": 100}
        results = []
        for page in range(1, max_pages + 1):
            params["page"] = page
            resp = self.get(path, params=params)
            if not resp:
                break
            data = resp.json()
            if not data:
                break
            results.extend(data)
            if 'rel="next"' not in resp.headers.get("Link", ""):
                break
        return results


# ---------------------------------------------------------------------------
# Per-repo fetchers
# ---------------------------------------------------------------------------

def fetch_languages(client, owner, repo):
    return client.get_json(f"/repos/{owner}/{repo}/languages") or {}


def fetch_contributors(client, owner, repo):
    raw = client.get_all_pages(f"/repos/{owner}/{repo}/contributors", max_pages=3)
    return [
        {
            "login": c["login"],
            "avatar_url": c["avatar_url"],
            "profile_url": c["html_url"],
            "commit_count": c["contributions"],
            "pr_count": 0,
        }
        for c in (raw or [])[:30]
    ]


def fetch_pr_counts(client, owner, repo):
    """Return dict of {login: pr_count} from the last ~200 closed PRs."""
    counts = {}
    pulls = client.get_all_pages(
        f"/repos/{owner}/{repo}/pulls",
        {"state": "closed", "sort": "updated"},
        max_pages=2,
    )
    for pr in pulls or []:
        if pr.get("user"):
            login = pr["user"]["login"]
            counts[login] = counts.get(login, 0) + 1
    return counts


def fetch_commit_activity(client, owner, repo):
    """Return list of 52 weekly commit totals (most recent last)."""
    for _ in range(4):
        data = client.get_json(f"/repos/{owner}/{repo}/stats/commit_activity")
        if data and isinstance(data, list):
            return [w.get("total", 0) for w in data[-52:]]
        time.sleep(2)
    return [0] * 52


def fetch_readme(client, owner, repo):
    data = client.get_json(f"/repos/{owner}/{repo}/readme")
    if not data:
        return None
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return content[:6000]
    except Exception:
        return None


def fetch_file(client, owner, repo, path):
    data = client.get_json(f"/repos/{owner}/{repo}/contents/{path}")
    if not data or isinstance(data, list):
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def extract_deps(client, owner, repo, languages):
    """Best-effort extraction of external dependency names."""
    lang_set = set(languages.keys())
    deps = []

    if lang_set & {"JavaScript", "TypeScript"}:
        content = fetch_file(client, owner, repo, "package.json")
        if content:
            try:
                pkg = json.loads(content)
                all_deps = {}
                all_deps.update(pkg.get("dependencies", {}))
                all_deps.update(pkg.get("devDependencies", {}))
                deps.extend(list(all_deps.keys())[:60])
            except json.JSONDecodeError:
                pass

    if "Python" in lang_set:
        py_deps = []
        for req_path in ["requirements.txt", "requirements/base.txt", "requirements/prod.txt"]:
            content = fetch_file(client, owner, repo, req_path)
            if content:
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-", "git+")):
                        name = re.split(r"[>=<!;\s\[]", line)[0].strip()
                        if name:
                            py_deps.append(name)
                break
        if not py_deps:
            content = fetch_file(client, owner, repo, "pyproject.toml")
            if content:
                # PEP 517/518 [project] dependencies array
                m = re.findall(r'\[project\].*?dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
                if not m:
                    m = re.findall(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
                if m:
                    for dep in re.findall(r'["\']([A-Za-z0-9][\w.\-]*)', m[0]):
                        py_deps.append(dep)
                # Poetry: [tool.poetry.dependencies] table format
                in_poetry_deps = False
                for line in content.splitlines():
                    if re.match(r'\[tool\.poetry\.dependencies\]', line):
                        in_poetry_deps = True
                    elif line.startswith("[") and in_poetry_deps:
                        in_poetry_deps = False
                    elif in_poetry_deps:
                        pm = re.match(r'^([\w][\w.\-]*)\s*=', line)
                        if pm and pm.group(1).lower() != "python":
                            py_deps.append(pm.group(1))
        deps.extend(py_deps)

    if lang_set & {"Swift"}:
        content = fetch_file(client, owner, repo, "Package.swift")
        if content:
            # Extract dependency repo names from GitHub-style URLs
            for m in re.finditer(r'url\s*:\s*"([^"]+)"', content):
                url = m.group(1)
                repo_name = url.rstrip("/").split("/")[-1]
                repo_name = re.sub(r"\.git$", "", repo_name, flags=re.IGNORECASE)
                if repo_name:
                    deps.append(repo_name)

    if lang_set & {"Kotlin", "Java", "Groovy", "Scala"}:
        for gradle_file in ["build.gradle.kts", "build.gradle"]:
            content = fetch_file(client, owner, repo, gradle_file)
            if content:
                for m in re.finditer(
                    r'(?:implementation|api|compileOnly|runtimeOnly|testImplementation|compile)\s*\(?["\']([^"\']+)["\']',
                    content,
                ):
                    coord = m.group(1)
                    parts = coord.split(":")
                    if len(parts) >= 2:
                        deps.append(parts[1])  # artifactId
                break

    if "Go" in lang_set:
        content = fetch_file(client, owner, repo, "go.mod")
        if content:
            for line in content.splitlines():
                m = re.match(r'\s+([\w./\-]+)\s+v[\d.]+', line)
                if m:
                    deps.append(m.group(1))

    if "Rust" in lang_set:
        content = fetch_file(client, owner, repo, "Cargo.toml")
        if content:
            in_deps = False
            for line in content.splitlines():
                if re.match(r'\[(dev-)?dependencies\]', line):
                    in_deps = True
                elif line.startswith("[") and in_deps:
                    in_deps = False
                elif in_deps:
                    m = re.match(r'^([\w][\w-]*)\s*=', line)
                    if m:
                        deps.append(m.group(1))

    if "Ruby" in lang_set:
        content = fetch_file(client, owner, repo, "Gemfile")
        if content:
            for line in content.splitlines():
                m = re.match(r"\s*gem\s+['\"]([^'\"]+)['\"]", line)
                if m:
                    deps.append(m.group(1))

    return list(dict.fromkeys(deps))[:60]  # deduplicate, limit


def build_internal_deps(repos_data, org):
    """Populate internal dependency edges by matching external dep names to repo names."""
    repo_names = {r["name"] for r in repos_data}

    def normalize(name):
        return name.lower().replace("-", "").replace("_", "").replace(".", "")

    normalized_map = {normalize(n): n for n in repo_names}

    for repo in repos_data:
        internal = set()
        for dep in repo["dependencies"]["external"]:
            # Strip scope prefix (e.g. @myorg/pkg -> pkg)
            clean = re.sub(r'^@[^/]+/', '', dep)
            # Exact match
            if clean in repo_names and clean != repo["name"]:
                internal.add(clean)
            else:
                # Normalized match: case-insensitive, ignore hyphens/underscores/dots
                norm = normalize(clean)
                if norm in normalized_map and normalized_map[norm] != repo["name"]:
                    internal.add(normalized_map[norm])
        repo["dependencies"]["internal"] = sorted(internal)


def process_repo(client, repo, org):
    name = repo["name"]
    owner = repo["owner"]["login"]

    languages = fetch_languages(client, owner, name)
    contributors = fetch_contributors(client, owner, name)

    try:
        pr_counts = fetch_pr_counts(client, owner, name)
        for c in contributors:
            c["pr_count"] = pr_counts.get(c["login"], 0)
        contributors.sort(key=lambda x: x["pr_count"], reverse=True)
    except Exception:
        pass

    commit_frequency = fetch_commit_activity(client, owner, name)
    readme = fetch_readme(client, owner, name)
    external_deps = extract_deps(client, owner, name, languages)

    return {
        "id": name,
        "name": name,
        "full_name": repo["full_name"],
        "description": repo.get("description") or "",
        "url": repo["html_url"],
        "created_at": repo.get("created_at", ""),
        "updated_at": repo.get("updated_at", ""),
        "pushed_at": repo.get("pushed_at", ""),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "is_private": repo.get("private", False),
        "is_archived": repo.get("archived", False),
        "is_fork": repo.get("fork", False),
        "default_branch": repo.get("default_branch", "main"),
        "topics": repo.get("topics", []),
        "languages": languages,
        "contributors": contributors,
        "commit_frequency": commit_frequency,
        "readme": readme,
        "dependencies": {
            "external": external_deps,
            "internal": [],  # populated after all repos are processed
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dotenv.load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch GitHub org data for org-repo-viz",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch.py my-org
  python fetch.py my-org --token ghp_xxxx
  GITHUB_TOKEN=ghp_xxxx python fetch.py my-org --skip-forks
  python fetch.py  # reads GITHUB_ORG and GITHUB_TOKEN from .env
        """,
    )
    parser.add_argument("org", nargs="?", default=None, help="GitHub organization name (or set GITHUB_ORG in .env)")
    parser.add_argument("--output", default="docs/data.json", help="Output path (default: docs/data.json)")
    parser.add_argument("--token", default=None, help="GitHub personal access token")
    parser.add_argument("--skip-forks", action="store_true", help="Skip forked repositories")
    parser.add_argument("--skip-archived", action="store_true", help="Skip archived repositories")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N repos (for testing)")
    args = parser.parse_args()

    org = args.org
    if org is None:
        org = os.environ.get("GITHUB_ORG")
    if not org:
        print("Error: GitHub organization required.")
        print("  Pass it as an argument or set GITHUB_ORG in .env")
        sys.exit(1)

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GitHub token required.")
        print("  Set GITHUB_TOKEN environment variable or pass --token <token>")
        print("  Token needs: read:org, repo (or public_repo for public-only)")
        sys.exit(1)

    client = GitHubClient(token)

    try:
        user = client.get_json("/user")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Authentication failed (401 Unauthorized).")
            print("  Possible causes:")
            print("    - Token is invalid, expired, or revoked")
            print("    - Token was copy-pasted incorrectly (check for extra spaces/newlines)")
            print("    - If using SSO, authorize the token for your org at:")
            print("      https://github.com/settings/tokens → Configure SSO")
            print("  Required scopes: repo (or public_repo), read:org")
            sys.exit(1)
        raise
    if not user:
        print("Error: Could not authenticate. Check your token.")
        sys.exit(1)
    print(f"Authenticated as: {user.get('login')}")

    print(f"\nFetching repos for org: {org}")
    repos = client.get_all_pages(f"/orgs/{org}/repos", {"type": "all", "sort": "updated"}, max_pages=50)

    if not repos:
        print(f"Error: No repos found for '{org}'. Check org name and token permissions.")
        sys.exit(1)

    if args.skip_forks:
        repos = [r for r in repos if not r.get("fork")]
    if args.skip_archived:
        repos = [r for r in repos if not r.get("archived")]
    if args.limit:
        repos = repos[: args.limit]

    print(f"Processing {len(repos)} repos...\n")

    repos_data = []
    for i, repo in enumerate(repos):
        print(f"  [{i+1:>3}/{len(repos)}] {repo['name']:<40}", end="", flush=True)
        try:
            repo_data = process_repo(client, repo, org)
            repos_data.append(repo_data)
            lang_count = len(repo_data["languages"])
            contrib_count = len(repo_data["contributors"])
            print(f"  {lang_count} langs  {contrib_count} contributors")
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\nBuilding internal dependency graph...")
    build_internal_deps(repos_data, org)
    edge_count = sum(len(r["dependencies"]["internal"]) for r in repos_data)
    print(f"Found {edge_count} internal dependency edges")

    output = {
        "org": org,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_repos": len(repos_data),
        "repos": repos_data,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    print(f"\nSaved: {out_path}  ({size_kb:.1f} KB)")
    print(f"\nNext steps:")
    print(f"  1. Preview locally:  open docs/index.html")
    print(f"  2. Publish:          git add docs/ && git commit -m 'Update viz data' && git push")
    print(f"                       Then enable GitHub Pages from Settings > Pages > Branch: main, Folder: /docs")


if __name__ == "__main__":
    main()
