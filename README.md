# org-repo-viz

Interactive force-directed graph of a GitHub organisation's repositories and their interdependencies.

## Host this in your org (5 minutes)

1. **Add this repo to your org.** GitHub does not allow forking a public repo as a private one, so pick the option that fits:
   - **Public**: click **Fork** and select your org as the destination.
   - **Private**: go to [github.com/new/import](https://github.com/new/import), paste this repo's URL, set visibility to private, and import.

2. **Create a Personal Access Token (PAT)** with `repo` (or `public_repo` for public-only) and `read:org` scopes:
   - Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   - Add it as a repository secret named `GH_TOKEN` under **Settings → Secrets and variables → Actions**.

3. **Enable GitHub Pages**: go to **Settings → Pages → Branch: `main` / Folder: `/docs`** and save.

4. **Run the workflow**: go to **Actions → Update visualization → Run workflow**.
   Data is fetched automatically every Monday at 03:00 UTC after that.

Your graph will be live at `https://<your-org>.github.io/<repo-name>/`.

---

## Local usage

```bash
# Set your GitHub token (needs read:org + repo or public_repo scope)
export GITHUB_TOKEN=ghp_xxxx

uv run fetch.py <your-org>
```

Then serve the `docs/` folder with a local HTTP server (required for the JSON data to load correctly):

```bash
# Python (built-in)
python3 -m http.server 8000

# Node.js
npx serve docs
```

Open `http://localhost:8000` in your browser to preview the graph.

## Creating a GitHub Token

`GITHUB_TOKEN` needs a Personal Access Token (PAT), **not** an SSH key.

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)** or **Fine-grained token**
3. Grant scopes: `repo` (or `public_repo`) and `read:org`
4. Copy the token and set it in your environment or `.env`:

```bash
GITHUB_TOKEN="ghp_yourActualTokenHere"
```

## Options

```
uv run fetch.py <org> [--output PATH] [--skip-forks] [--skip-archived] [--limit N]
```

| Flag | Default | Description |
|---|---|---|
| `--output` | `docs/data.json` | Output path for the JSON data |
| `--skip-forks` | false | Skip forked repositories |
| `--skip-archived` | false | Skip archived repositories |
| `--limit N` | all | Process at most N repos (useful for testing) |

## Features

- Force-directed graph layout with draggable nodes
- Node tiles showing repo name, description, stars, badges
- Expandable sections per node: Created date, Contributors, Commit activity, Languages, Dependencies, README
- Expanded sections stay visible even when Details is collapsed
- **Settings sidebar**: toggle orphan/standalone nodes, expand any section for all nodes at once
- **Stats sidebar**: total repos & contributors, LoC by language, aggregate commit graph, popular external deps & top contributors with hover-to-highlight
- Hover a repo → dims unrelated nodes
- Hover a dep or contributor in the Stats sidebar → highlights all repos that use/include them
- Pan (drag background) and scroll-to-zoom

## What counts as an internal dependency?

`fetch.py` reads package files (`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`) and cross-references discovered dependency names against the list of repos in the org. Matches become graph edges.
