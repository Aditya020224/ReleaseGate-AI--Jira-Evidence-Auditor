from __future__ import annotations
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from src.config import settings
from src.jira_client import JiraClient
def extract_existing_source_map(
    jira: JiraClient, project_key: str, dataset_label: str
) -> Dict[str, str]:
    """Find already-imported issues so re-running the importer is idempotent."""
    jql = f'project = "{project_key}" AND labels = "{dataset_label}"'
    issues = jira.search_jql(jql, fields=["labels"])
    source_to_key: Dict[str, str] = {}
    for issue in issues:
        for lbl in issue.get("fields", {}).get("labels", []):
            if lbl.startswith("source-"):
                source_id = lbl[len("source-") :]
                source_to_key[source_id] = issue["key"]
    return source_to_key
def build_formatted_description(record: Dict[str, Any]) -> str:
    """Preserve all metadata explicitly inside the Jira description."""
    header = (
        f"Source ID: {record['source_id']}\n"
        f"Kind: {record['kind']}\n"
        f"Record Release: {record.get('release', 'N/A')}\n"
        f"Recorded Jira Status: {record.get('recorded_status', 'N/A')}\n"
        f"{'-' * 40}\n"
    )
    return header + record.get("description", "")
def import_single_record(
    jira: JiraClient,
    project_key: str,
    dataset_label: str,
    record: Dict[str, Any],
    existing_key: str | None,
) -> Tuple[str, str, bool]:
    """Create an issue and its comments if not already present."""
    source_id = record["source_id"]
    if existing_key:
        return source_id, existing_key, False
    kind_label = f"rr-{record['kind']}"
    source_label = f"source-{source_id}"
    labels = [dataset_label, kind_label, source_label]
    if record.get("release"):
        labels.append(f"rel-{record['release']}")
    summary = f"[{source_id}] {record['summary']}"
    description = build_formatted_description(record)
    issue_key = jira.create_issue(
        project_key=project_key,
        summary=summary,
        description_text=description,
        labels=labels,
    )
    for comment_text in record.get("comments", []):
        jira.add_comment(issue_key, comment_text)
    return source_id, issue_key, True
def run_import(dataset_path: str, project_key: str, workers: int = 6) -> None:
    settings.validate()
    start_time = time.time()
    raw_data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    dataset_label: str = raw_data["dataset_label"]
    records: List[Dict[str, Any]] = raw_data["records"]
    jira = JiraClient(settings.JIRA_BASE_URL, settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
    print(f"Checking existing issues in {project_key} with label '{dataset_label}'...")
    source_to_key = extract_existing_source_map(jira, project_key, dataset_label)
    print(f"Found {len(source_to_key)} existing records. Total in dataset: {len(records)}.")
    created_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                import_single_record,
                jira,
                project_key,
                dataset_label,
                rec,
                source_to_key.get(rec["source_id"]),
            )
            for rec in records
        ]
        for idx, future in enumerate(as_completed(futures), 1):
            source_id, key, created = future.result()
            source_to_key[source_id] = key
            if created:
                created_count += 1
            if idx % 25 == 0 or idx == len(records):
                print(f"Processed {idx}/{len(records)} records (newly created: {created_count})...")
    print("Linking related issues...")
    link_type = jira.get_link_type_name()
    existing_pairs: Set[Tuple[str, str]] = set()
    jql = f'project = "{project_key}" AND labels = "{dataset_label}"'
    for issue in jira.search_jql(jql, fields=["issuelinks"]):
        src_k = issue["key"]
        for link in issue.get("fields", {}).get("issuelinks", []):
            if "outwardIssue" in link:
                existing_pairs.add((src_k, link["outwardIssue"]["key"]))
    links_created = 0
    for rec in records:
        src_id = rec["source_id"]
        src_key = source_to_key.get(src_id)
        for target_id in rec.get("links", []):
            tgt_key = source_to_key.get(target_id)
            if src_key and tgt_key and (src_key, tgt_key) not in existing_pairs:
                jira.create_issue_link(inward_key=src_key, outward_key=tgt_key, link_type=link_type)
                existing_pairs.add((src_key, tgt_key))
                links_created += 1
    elapsed = round(time.time() - start_time, 2)
    print(
        f"Import complete in {elapsed}s. Created {created_count} issues and {links_created} new links."
    )
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import dataset.json into Jira Cloud.")
    parser.add_argument("--dataset", default="inputs/dataset.json", help="Path to dataset.json")
    parser.add_argument("--project", default=settings.JIRA_PROJECT_KEY, help="Jira project key")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent import threads")
    args = parser.parse_args()
    run_import(args.dataset, args.project, args.workers)
