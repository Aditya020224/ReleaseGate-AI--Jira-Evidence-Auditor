# Jira Release Evidence Agent
A tool-using AI agent that investigates release evidence stored in Jira Cloud and produces an evidence-backed 
release-readiness decision.

## Setup & Execution
1. **Create a Jira Cloud Project**:
   - Create a free Jira Cloud workspace and a new project (key `REL`).
   - Generate an Atlassian API token from `https://id.atlassian.com/manage-profile/security/api-tokens`.

2. **Install Dependencies**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   
   # source .venv/bin/activate  # Mac/Linux
   pip install -r requirements.txt
   ```

3. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Fill in JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY, and GEMINI_API_KEY
   ```

4. **Import Dataset into Jira (Idempotent)**:
   ```bash
   python -m src.importer --dataset inputs/dataset.json --project REL
   ```

5. **Run the Release Evidence Agent**:
   ```bash
   python -m src.agent --project REL --dataset-label tyn-release-assessment-v2 --release R2.4
   ```
   
## Design Choices & Trade-offs
- **Scope Isolation**: Every imported ticket is tagged with `tyn-release-assessment-v2`, `rr-<kind>`, and 
`source-<id>`. The agent strictly filters all JQL queries by `dataset_label` so unrelated project issues 
never pollute the assessment.
- **Per-Requirement Bounded Loops**: Rather than stuffing 400 issues into one massive context window, the 
agent evaluates each of the 12 manifest requirements in an isolated, bounded (`max_turns=8`) tool-calling 
loop, following Jira issue links dynamically.
- **Context Window & Noise Management**: High-comment tickets (such as `REC-5957` with 64 comments) 
automatically truncate repetitive middle logs while preserving initial context and the latest QA outcomes, 
with a pagination tool available if deeper inspection is needed.
- **Prompt Injection Mitigation**: System instructions explicitly sandbox all Jira issue text as untrusted 
data, preventing embedded overrides (such as `REC-5716`) from altering assessment rules.
- **Known Limitations**: Jira Cloud's native author and creation timestamps belong to the API token owner; 
therefore, the importer preserves the scenario's `Recorded event <timestamp> | actor <name> | role <role>` 
headers verbatim inside comment bodies.

## AI Assistance Disclosure
- AI coding assistance was used to scaffold the Jira REST API v3 ADF serialization, retry logic, and CLI 
boilerplate. All architectural design, rule enforcement, and verification against the dataset were reviewed 
and validated manually.