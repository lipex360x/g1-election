# G1 Election Abroad — Second-Round Results Scraper

> **Project handoff / AI assistant entry point:** This README documents the repository, its execution lifecycle, operational commands, dashboard contract, failure-recovery policy, and known data limitations. Read it before modifying the project or responding to a request to run, troubleshoot, or display the scraper.

## Purpose and scope

This repository collects **country-level votes cast abroad in Brazil's 25 October 2026 presidential second round**, comparing **Lula** and **Flávio Bolsonaro**, from a continuously edited G1 news article. It produces a ranked CSV and Excel workbook, plus machine-readable run status and execution history. A **ChatGPT interactive dashboard is generated in the conversation from the published CSV**; it is **not** a hosted application or a dashboard implemented in this repository.

- Repository: https://github.com/lipex360x/g1-election
- G1 source: https://g1.globo.com/mundo/noticia/2026/10/25/votacao-no-exterior-confira-os-resultados-do-2o-turno-entre-lula-e-flavio-bolsonaro.ghtml
- Workflow: https://github.com/lipex360x/g1-election/actions/workflows/scrape.yml
- Latest data: https://github.com/lipex360x/g1-election/blob/main/output/ranking.csv
- Official election results are issued by Brazil's TSE; this scraper captures a **partial third-party media report**, not certified national totals.

## Architecture at a glance

```text
User / ChatGPT
    |
    | manual workflow_dispatch (or rerun an eligible existing job)
    v
GitHub Actions: .github/workflows/scrape.yml
    | checkout -> Python 3.11 -> install requirements
    | python scraper.py   [EXACTLY ONCE]
    v
G1 article -> requests/BeautifulSoup/pandas parsers
    |
    +--> output/ranking.csv, output/ranking.xlsx
    +--> output/status.json
    +--> output/debug.html, output/article_text.txt (local diagnostics)
    |
    v
Workflow appends output/execution_log.jsonl
    | commits status/log/CSV/XLSX to main
    | uploads output/ as GitHub Actions artifact
    v
ChatGPT reads latest run + status + CSV -> interactive GenUI dashboard
```

**Critical scheduling invariant:** The workflow has **only `workflow_dispatch`**. There is **no cron schedule, no push trigger, no polling loop, and no repeated invocation inside a run**. Do not add any of those unless the user explicitly requests a change. One workflow attempt invokes `python scraper.py` once.

## Repository files

| Path | Role |
| --- | --- |
| `scraper.py` | HTTP fetch, HTML diagnostics, country/second-round parsing, deduplication, CSV/XLSX output and status JSON |
| `.github/workflows/scrape.yml` | Manual GitHub Actions workflow; runs scraper once, appends execution history, commits generated files, uploads artifact |
| `requirements.txt` | Python dependencies: requests, BeautifulSoup, pandas, lxml, openpyxl |
| `output/ranking.csv` | UTF-8 with BOM, country-level ranked results; **primary dashboard input** |
| `output/ranking.xlsx` | Excel export of the same ranked results |
| `output/status.json` | Most recently **published** scrape status, diagnostics, timestamps and run URL |
| `output/execution_log.jsonl` | Append-only JSON Lines record of runs **successfully persisted to the branch** |
| `output/debug.html` | Downloaded raw page for debugging; not explicitly staged by the workflow |
| `output/article_text.txt` | Parsed article text diagnostic; not explicitly staged by the workflow |

### CSV schema

`País,Lula,Flávio,Total,Diferença Lula-Flávio,Fonte`

- `País`: country/territory name as extracted from G1.
- `Lula`, `Flávio`: nonnegative integer vote counts.
- `Total`: sum of the two candidate counts in that row.
- `Diferença Lula-Flávio`: Lula minus Flávio.
- `Fonte`: article URL.
- Rows are sorted by descending `Total`. The dashboard aggregates `Lula` and `Flávio` from this CSV, not from the article's headline totals.

### Status and execution log

`output/status.json` includes `url`, `fetched_at_utc`, `status`, HTTP/HTML diagnostics, and (on successful extraction) `countries`, `lula`, `flavio`. The workflow adds `updated_at_utc` and `run_url`. Possible scraper statuses include `started` (intermediate), `success`, `no_structured_results`, and `error`.

Each line in `output/execution_log.jsonl` is an independent JSON object with `timestamp_utc`, `source_fetched_at_utc`, `status`, `countries`, `error`, and `run_url`.

**Important distinction:** GitHub Actions' latest run status and the committed `output/status.json` may refer to **different attempts**. If a job fails before its commit/push, the branch may still show the prior successful snapshot. Never treat a historical `status: success` as proof that the newest workflow attempt succeeded. Check both the Actions API and the committed file timestamps/run URLs.

## How the scraper works

1. `main()` sends a `requests.get` to the fixed G1 URL, with a browser-like User-Agent and a 35-second timeout.
2. It records HTTP status, final URL, HTML size, page title, article/table/script counts, candidate-name presence and excerpts for diagnostics. It writes the response to `output/debug.html`.
3. `parse_country_sections(html)` is the **primary parser**. It looks for country headings followed by `2º turno` blocks and extracts a Lula/Flávio pair even when the label, colon, candidate name, and vote count span multiple lines. It stops a country section at first-round labels or the 2022 comparison.
4. `parse_tables(html)` is a fallback for HTML tables with recognizable country, Lula and Flávio columns.
5. `parse_embedded_json(html)` recursively searches embedded JSON / JSON-LD for objects with a country and both candidate counts.
6. `parse_lines(html)` exists as an additional text-pattern helper, **but is not currently called by `main()`**. Do not assume it contributes to the output.
7. All active parser results are combined and deduplicated by case-folded country name. **Conflicting counts for the same country raise an error.** The parser converts Brazilian thousands separators (e.g. `28.538`) to integers.
8. If there are no valid rows, the status is `no_structured_results`; it does **not** fabricate votes or overwrite the CSV/XLSX with fake results.
9. If rows exist, pandas computes `Total` and `Diferença Lula-Flávio`, sorts by total votes, writes `ranking.csv` and `ranking.xlsx`, and marks `status: success` with aggregate counts.
10. Errors are caught and written into `status.json`. **Implementation caveat:** `main()` currently catches exceptions and does not re-raise them, so `python scraper.py` can exit with code 0 even when `status: error` or `no_structured_results`. Inspect the JSON status rather than relying solely on the process exit code.

## GitHub Actions lifecycle

Current workflow file: `.github/workflows/scrape.yml`.

1. Trigger manually with **Actions -> Scrape G1 results -> Run workflow** on `main`. A permitted GitHub API `workflow_dispatch` action may also be used if available.
2. The `scrape` job checks out the repository, sets up Python 3.11, and installs dependencies.
3. The step **Scrape once and append execution log** runs `python scraper.py` once; its shell wrapper reads `output/status.json`, adds timestamps and the Actions run URL, appends one JSONL history entry, then exits with the Python process exit code.
4. The **Persist status, log and results** step runs with `if: always()`. It force-adds status/log plus any CSV/XLSX files, commits only when there are staged changes, then performs:
   ```bash
   git fetch origin main
   git rebase origin/main
   git push origin HEAD:main
   ```
   This rebase-before-push behavior was added after a failed rerun encountered a non-fast-forward rejection (`HEAD -> main (fetch first)`). It avoids that specific stale-checkout push failure. A real merge conflict or other git error can still fail the job.
5. The final **actions/upload-artifact@v4** step runs with `if: always()`, uploading `output/` as artifact `g1-scrape-output`, even on failure where files exist.
6. The workflow has `permissions: contents: write`, `concurrency.group: g1-scraper`, `cancel-in-progress: false`, and a nine-minute job timeout. It commits output with `[skip ci]`.

**Rerun semantics:** A GitHub Actions **rerun uses the original run's commit**, not necessarily the current `main`. After editing the workflow or scraper, **do not rerun an older failed job to test the fix**; start a **new manual workflow_dispatch run on the corrected commit**. The connected GitHub tooling may expose `rerun_workflow_job` but not a dispatch operation. If dispatch is unavailable, give the user the workflow link and explain that a new manual run is required; do not claim to have started it.

## Local development

Requires Python 3.11+ (3.11 is the Actions version):

```bash
git clone https://github.com/lipex360x/g1-election.git
cd g1-election
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scraper.py
```

On Windows, activate with `.venv\\Scripts\\activate`. Inspect `output/status.json`, `output/ranking.csv`, and `output/debug.html` after a run. The scraper writes output relative to the **current working directory**; run it from the repository root.

## ChatGPT / interactive dashboard contract

The dashboard is rendered **inside a ChatGPT conversation**, using interactive GenUI controls and the latest successfully published CSV. It is not committed as a standalone web frontend.

For a request such as **"update the panel"**, **"X"**, or **"check the latest workflow"**:

1. Query the latest GitHub Actions workflow run (including `run_attempt`, `status`, `conclusion`, `head_sha`, timestamps and `html_url`).
2. If the latest run is **failed**, inspect its job steps and full job logs, identify the failing step, fix the underlying issue in the repository where possible, and arrange **one** corrected execution. **Do not rebuild the dashboard from old CSV data after a failure.** Provide the run URL for monitoring. Before requesting manual dispatch, check whether an existing run on the corrected commit is eligible for an immediate single-job rerun via `rerun_workflow_job`. Request manual dispatch only if a new commit must be used and no dispatch tool is available.
3. If the latest run is **in progress**, report its status and URL; do not present previous results as fresh.
4. Only if the latest run **succeeded**, fetch `output/status.json`, `output/ranking.csv`, and optionally `output/execution_log.jsonl`. Verify the published `run_url` and timestamps correspond to the successful run; verify CSV row counts and candidate totals. If publishing is stale or inconsistent, investigate instead of silently displaying outdated data.
5. Rebuild the interactive panel from actual CSV rows. Show the source timestamp, GitHub run URL, number of countries, vote totals, candidate percentages, a proportional stacked bar, and per-country results. Provide country search, sorting, candidate filter, and show-more controls.
6. **Fixed candidate colors:** Lula = **red `#D45252`**; Flávio Bolsonaro = **blue `#287EC4`**. Do not reverse them.
7. **Mandatory footer buttons at the bottom of every successful dashboard:**
   - **"Rerun scraper — executar uma vez"**: starts a new conversational request to execute the scraper **exactly once**, using an eligible one-shot job rerun or a new manual dispatch. First check the run/commit and available actions. Do not trigger repeated runs.
   - **"Atualizar resultados"**: starts a new conversational request to check the latest run and regenerate the dashboard **only after a verified successful new/published collection**. This button must **not** itself start a scrape.
8. Buttons in ChatGPT are conversational controls (e.g. `GenUI.issueNewTurn(...)`), not GitHub-hosted controls. A button requests an action; success must be confirmed by the GitHub tool response.
9. When data are unchanged after a successful new scrape, say so explicitly. Never invent updates, percentages, countries or vote totals.

### Useful GitHub operations for assistants

- Inspect runs: `GET https://api.github.com/repos/lipex360x/g1-election/actions/runs?per_page=5`; filter for the `Scrape G1 results` workflow.
- Inspect jobs: `GET /repos/lipex360x/g1-election/actions/runs/{run_id}/jobs` or connected `fetch_workflow_run_jobs`.
- Inspect failing job logs: connected `fetch_workflow_job_logs` with the current job ID.
- Read repository files: connected `fetch_file` for `scraper.py`, `.github/workflows/scrape.yml`, `output/status.json`, `output/ranking.csv`, etc.
- Edit repository: connected `update_file` using the file's current blob SHA, then verify the returned commit SHA.
- Rerun an **eligible** job: connected `rerun_workflow_job` with the job ID. Remember that this uses the original commit.
- New corrected run: https://github.com/lipex360x/g1-election/actions/workflows/scrape.yml

## Failure recovery playbook

| Symptom | Diagnosis | Correct response |
| --- | --- | --- |
| `Persist status, log and results` fails with `[rejected] HEAD -> main (fetch first)` | Branch moved after checkout | Use the current workflow's snapshot + `git fetch origin main` + `git reset --hard origin/main` + restore generated outputs + append log + commit/push; do not rebase changing JSONL/XLSX output |
| Scrape step fails | HTTP/network/parser/dependency error | Inspect full logs and `status.json`/artifact diagnostics; fix root cause, commit, then run corrected version |
| Workflow reports success but `status.json` is `error` or `no_structured_results` | Python script swallows exceptions | Treat as a **data collection failure**, do not render stale results; fix script/status handling |
| New run succeeds but branch CSV timestamp or totals are unchanged | Either genuinely unchanged source or stale publication | Compare run URL, timestamps and CSV; distinguish unchanged source from failed/stale publishing |
| Country totals conflict or unexpectedly duplicate | Fragile article HTML parsing, ambiguous headings or repeated text | Inspect `article_text.txt` and raw HTML; verify against source; avoid silently inventing or correcting figures |
| New workflow run is still running | Incomplete | Return run URL and wait for verified success before rebuilding panel |

## Data quality and limitations

- G1 updates the article during election coverage. Its headline summary may differ from the sum of country rows or may include more countries than the parser currently extracts.
- The current parser uses heuristic heading recognition. It can misidentify headings or associate neighboring country text. In the 25 October snapshot, **Finland and Estonia** both show 550/185, and **Singapore and Syria** both show 213/121; these duplicated pairs should be reviewed against the original source before assuming they are errors or valid.
- **Never describe CSV totals as official complete election results.** This is a partial extraction of a media report, subject to verification.
- Missing countries or unavailable vote counts must remain missing; do not substitute zero for unknown or fabricate rows.
- The site can change structure or restrict automated requests. HTML/JSON parser logic and dependencies may require maintenance.
- A successful GitHub job proves execution/publishing, **not independent verification of every extracted vote count**.

## Verified reference state (historical example, not a live guarantee)

At **2026-10-25 18:41 UTC**, workflow run [40222391992](https://github.com/lipex360x/g1-election/actions/runs/40222391992) completed successfully on commit `6cc0479006ab91696b99d651e617d68af67ec6c9`. Published `status.json` recorded `fetched_at_utc=2026-10-25T18:41:07.466956+00:00`, `updated_at_utc=2026-10-25T18:41:10.016519+00:00`, **51 countries**, **96,413 Lula votes**, and **65,963 Flávio votes**. These are a historical snapshot; **always fetch the latest run and files** for a new request.

## Mandatory rerun-first decision rule for ChatGPT assistants

**Do not send the user to GitHub Actions merely because `workflow_dispatch` is absent from the connected GitHub tools.** This repository's GitHub connector exposes `rerun_workflow_job`, which has successfully been used to start a single new attempt of an existing `scrape` job.

When the user explicitly asks to **run, rerun, refresh the scraper, or test the workflow**, follow this exact order:

1. Inspect the newest `Scrape G1 results` run, its `head_sha`, `run_attempt`, and job IDs. Inspect the current `main` workflow and determine whether the target run's commit includes the desired one-shot scraper configuration and any required fixes.
2. If the existing run's commit is **eligible**, use the connected GitHub action **`rerun_workflow_job({repo_full_name:"lipex360x/g1-election",job_id:<scrape_job_id>})` immediately**, including when the prior job succeeded. A successful prior run can still be rerun to collect fresh data. Execute **only one** rerun call. Confirm that the tool returns `success: true`, then provide `https://github.com/lipex360x/g1-election/actions/runs/<run_id>` and, where possible, verify the attempt incremented and is queued or running.
3. If the existing run's commit is **ineligible because fixes were committed later**, do **not** rerun it and pretend it uses the new code. First look for an authorized GitHub action capable of dispatching the workflow at current `main`. If no such action exists, clearly explain that **this specific corrected version requires a new workflow_dispatch run** and provide the manual workflow link. This is a **fallback**, not the default.
4. If a rerun call is rejected, report the actual tool error and any permission limitation; do not claim a run started.
5. **Never treat `workflow_dispatch` as the only way to start a new collection.** Distinguish a **new workflow run** from a **new attempt of an existing run**. Both can execute the scraper once; the rerun preserves the original commit.
6. After requesting a rerun, **do not display an old CSV as a new result**. If the attempt fails, investigate logs, fix the cause, and arrange an eligible corrected run when possible. If it succeeds, validate the published status and CSV before rendering the dashboard.

**Concrete verified example:** On 2026-10-25, the assistant called `rerun_workflow_job` for job `121259190798` from run `40223253279` (commit `8eb0ba62de24e42356205704d147aa204e95ba71`). GitHub returned `success: true` and the run changed to `queued`, `run_attempt: 2`. Therefore, saying "the connector can only rerun jobs, so you must manually click Run workflow" was **incorrect for this eligible run**.

## Instructions for a fresh ChatGPT conversation

Paste this prompt after linking the repository:

> Read `README.md` in `lipex360x/g1-election` and follow its operational contract. **First trigger exactly one fresh collection autonomously**: inspect the latest workflow run and its `scrape` job; if its commit contains the current required fixes, call the connected GitHub `rerun_workflow_job` tool even if that job previously succeeded. **Do not ask me to click Run workflow merely because `workflow_dispatch` is unavailable.** Only require a new manual dispatch when the existing run's commit is outdated and no dispatch tool exists. Confirm GitHub accepted the rerun and send its run URL. Then check the newest attempt's status, timestamps and CSV. If it fails, inspect logs, fix the root cause and arrange a corrected execution where possible; **never rebuild the panel from stale results**. If it succeeds, validate the published CSV/status and build the interactive dashboard with **Lula red (#D45252)** and **Flávio Bolsonaro blue (#287EC4)**, with **Rerun scraper** and **Atualizar resultados** buttons at the **bottom**. Never introduce scheduling or loops without explicit permission.
