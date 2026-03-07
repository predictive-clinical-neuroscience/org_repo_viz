# org-repo-viz

Interactive force-directed graph of a GitHub organisation's repositories and their interdependencies.

## Quick start

```bash
pip install requests

# Set your GitHub token (needs read:org + repo or public_repo scope)
export GITHUB_TOKEN=ghp_xxxx

python fetch.py <your-org>
```

Open `docs/index.html` in your browser to preview the graph.

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
python fetch.py <org> [--output PATH] [--skip-forks] [--skip-archived] [--limit N]
```

| Flag | Default | Description |
|---|---|---|
| `--output` | `docs/data.json` | Output path for the JSON data |
| `--skip-forks` | false | Skip forked repositories |
| `--skip-archived` | false | Skip archived repositories |
| `--limit N` | all | Process at most N repos (useful for testing) |

## Publish to GitHub Pages

```bash
git add docs/
git commit -m "Update viz data"
git push
```

Then go to **Settings → Pages → Branch: `main` / Folder: `/docs`** and save. Your graph will be live at `https://<you>.github.io/<repo>/`.

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
