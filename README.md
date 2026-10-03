# Research Idea Agent

A local research workbench for developing **original, consequential, technically credible** ideas in AI and machine learning.

Create a research question, bring your sources, and develop a small set of research directions. Compare mechanisms and prior work, inspect citations, correct assumptions, and return to the project later.

## What works in this release

- OpenAI-compatible Chat Completions APIs with configurable endpoint, model, output format and token parameter.
- Autonomous, bounded rounds of literature discovery and proposal development.
- A visible initial proposal followed by targeted, model-planned English literature queries.
- Separate innovation, impact and feasibility reasoning for each direction.
- Object / intervention site / operation / signal / output mechanism diagrams.
- Source-linked claims and comparisons; unknown source IDs are rejected before saving.
- Live research events, checkpoint pause/resume, cancellation, version history and JSON export.
- Typed user corrections and project-scoped, conditional research notes.
- SQLite persistence, cached arXiv abstracts, and user-provided source passages.

This is an early implementation. Literature search currently uses **arXiv abstracts**; full-text reading requires imported passages. There is no automated experiment execution. Conditional notes are manually curated and project-scoped; automatic cross-project experience distillation is not yet implemented. Research assessments are model-generated proposals, not measured scientific outcomes.

## Run locally

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+ or 22.12+.

```sh
git clone https://github.com/maple1999/research-idea-agent.git
cd research-idea-agent
uv sync
```

Model settings can be entered in **运行设置 → 模型服务** after starting the app. Save once to apply them to the next model call, without restarting. In-flight calls finish using their original configuration. A blank key field preserves the saved key; changing the endpoint requires its key.

Alternatively, copy `.env.example` to `.env` to supply initial defaults:

```dotenv
IDEA_API_BASE=https://your-provider.example/v1
IDEA_API_KEY=your-local-key
IDEA_MODEL=your-model-name
IDEA_OUTPUT_MODE=json_object
IDEA_TOKEN_PARAMETER=max_tokens
```

Then build the interface and start one local backend worker:

```sh
cd web
npm ci
npm run build
cd ..
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765**. For frontend development, run `npm run dev` inside `web` and visit port 5173 while the backend is running.

Keep a single backend worker: this release's active-task coordinator is in process. The database preserves projects and checkpoints across restarts; interrupted runs return as paused for manual resumption.

## Provider compatibility

| Setting | Options |
|---|---|
| `IDEA_OUTPUT_MODE` | `json_schema`, `json_object` (default), `text` |
| `IDEA_TOKEN_PARAMETER` | `max_tokens` (default), `max_completion_tokens` |
| `IDEA_MAX_OUTPUT_TOKENS` | Per-call output limit, default 3500 |
| `IDEA_DATA_DIR` | Local SQLite data directory, default `data` |

Choose the format supported by your service. In all modes, responses are validated locally. Endpoint errors do not trigger automatic paid retries or silent fallback to another model. Keys remain server-side. Project materials are sent to the configured model service during a run; arXiv receives literature queries when search is enabled.

Settings saved through the UI persist in `data/provider-settings.json` (or `IDEA_DATA_DIR`), which is excluded from Git. This local file includes the key; the API never returns it. Saved UI settings take precedence over `.env` on subsequent starts. Saving changes configuration only; it does not make a paid test request. Exploration budgets still apply to the next research round.

## Controls and budgets

Each run has call, token and active-time limits. Before a call, the app reserves a conservative UTF-8-size input estimate plus the output limit. Returned usage replaces that reservation when available. Providers differ in token accounting, so the token limit is an application estimate, not a billing guarantee. Call limits are enforced before dispatch. Fees are not estimated in this release.

Pause completes the current request and stops subsequent work. Cancel discards its eventual proposal while accounting for usage. A correction advances the project revision: output generated from an older revision cannot overwrite it. After a crash, unknown in-flight usage stays reserved. A browser disconnect does not stop research.

## Development checks

```sh
uv run pytest -q
uv run ruff check app tests
cd web
npm run build
```

Tests use explicit fixture providers and transports. The production app never fabricates a run when a key is absent. Browser integration tests are documented in `web/tests` and run with `npm run test:e2e` after installing Playwright Chromium.

```sh
cd web
npx playwright install chromium
npm run test:e2e
```

Stop any local server on port 8765 before the browser test: it starts a separate server with temporary test data. On Windows, if pytest cannot access an existing system temporary directory, create `.private` and use `uv run pytest -q --basetemp=.private/pytest-local`.

## Project layout

```text
app/            API, SQLite store, research coordinator, model and literature adapters
web/src/        Research workbench and mechanism view
tests/          Runtime, API, budget, provenance and provider contract checks
data/           Private local projects and sources (ignored)
```

The repository contains the application and public usage documentation. Credentials, research sessions and local materials are excluded from version control.

## References

Implementation is original. Design references include [ResearchStudio](https://github.com/microsoft/ResearchStudio), [OpenAI4S](https://github.com/PKU-YuanGroup/OpenAI4S), [Scideator](https://arxiv.org/abs/2409.14634), [IDEAgent](https://arxiv.org/abs/2607.22375), and [AIM](https://arxiv.org/abs/2609.38445). No source code from these projects is bundled.

The compatible provider follows the [Chat Completions interface](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and configurable [structured-output formats](https://developers.openai.com/api/docs/guides/structured-outputs).
