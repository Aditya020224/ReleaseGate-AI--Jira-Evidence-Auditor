from __future__ import annotations
import time
from typing import Any, Dict, List
from src.jira_client import JiraClient, adf_to_text
class JiraReleaseTools:
    """Bounded Jira investigation tools exposed to the LLM agent."""
    def __init__(self, jira: JiraClient, project_key: str, dataset_label: str):
        self.jira = jira
        self.project_key = project_key
        self.dataset_label = dataset_label
        self.trace: List[Dict[str, Any]] = []
        self._source_to_key_cache: Dict[str, str] = {}
    def _resolve_issue_key(self, identifier: str) -> str:
        """Accept either a Jira key (e.g., REL-12) or a source_id (e.g., REQ-01, REC-2081)."""
        ident = identifier.strip()
        if ident in self._source_to_key_cache:
            return self._source_to_key_cache[ident]
        if ident.startswith(f"{self.project_key}-"):
            return ident
        jql = (
            f'project = "{self.project_key}" AND labels = "{self.dataset_label}" '
            f'AND labels = "source-{ident}"'
        )
        issues = self.jira.search_jql(jql, fields=["summary"], max_results=2)
        if not issues:
            raise ValueError(f"No issue found in scope '{self.dataset_label}' for '{ident}'.")
        key = issues[0]["key"]
        self._source_to_key_cache[ident] = key
        return key
    def get_manifest_and_requirements(self) -> Dict[str, Any]:
        """Fetch the release manifest and all requirement tickets in the dataset scope."""
        jql = (
            f'project = "{self.project_key}" AND labels = "{self.dataset_label}" '
            f'AND labels in ("rr-manifest", "rr-requirement")'
        )
        issues = self.jira.search_jql(
            jql, fields=["summary", "description", "labels", "issuelinks"]
        )
        manifest = None
        requirements = []
        for issue in issues:
            fields = issue.get("fields", {})
            labels = fields.get("labels", [])
            source_id = next((l[7:] for l in labels if l.startswith("source-")), issue["key"])
            self._source_to_key_cache[source_id] = issue["key"]
            linked = self._extract_links(fields.get("issuelinks", []))
            item = {
                "jira_key": issue["key"],
                "source_id": source_id,
                "summary": fields.get("summary", ""),
                "description": adf_to_text(fields.get("description")).strip(),
                "linked_issues": linked,
            }
            if "rr-manifest" in labels:
                comments_data = self.jira.get_comments(issue["key"], start_at=0, max_results=20)
                item["comments"] = [
                    adf_to_text(c.get("body")).strip()
                    for c in comments_data.get("comments", [])
                ]
                manifest = item
            else:
                requirements.append(item)
        requirements.sort(key=lambda r: r["source_id"])
        return {"manifest": manifest, "requirements": requirements}
    def _extract_links(self, issuelinks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        links = []
        for link in issuelinks:
            if "outwardIssue" in link:
                target = link["outwardIssue"]
                direction = link.get("type", {}).get("outward", "relates to")
            elif "inwardIssue" in link:
                target = link["inwardIssue"]
                direction = link.get("type", {}).get("inward", "relates to")
            else:
                continue
            links.append(
                {
                    "direction": direction,
                    "jira_key": target["key"],
                    "summary": target.get("fields", {}).get("summary", ""),
                }
            )
        return links
    def get_issue_details(self, identifier: str) -> Dict[str, Any]:
        """Inspect a ticket's description, links, and comments (with smart tail windowing)."""
        key = self._resolve_issue_key(identifier)
        issue = self.jira.get_issue(key)
        fields = issue.get("fields", {})
        labels = fields.get("labels", [])
        if self.dataset_label not in labels:
            return {"error": f"Issue {key} is outside dataset scope '{self.dataset_label}'."}
        source_id = next((l[7:] for l in labels if l.startswith("source-")), key)
        comments_resp = self.jira.get_comments(key, start_at=0, max_results=100)
        total_comments = comments_resp.get("total", 0)
        raw_comments = comments_resp.get("comments", [])
        truncated = False
        if len(raw_comments) > 20:
            raw_comments = raw_comments[:2] + raw_comments[-15:]
            truncated = True
        formatted_comments = [
            {
                "index": idx,
                "text": adf_to_text(c.get("body")).strip(),
            }
            for idx, c in enumerate(raw_comments)
        ]
        return {
            "jira_key": key,
            "source_id": source_id,
            "summary": fields.get("summary", ""),
            "labels": labels,
            "description": adf_to_text(fields.get("description")).strip(),
            "linked_issues": self._extract_links(fields.get("issuelinks", [])),
            "total_comments": total_comments,
            "comments_truncated": truncated,
            "comments": formatted_comments,
        }
    def get_issue_comments_page(
        self, identifier: str, start_at: int = 0, limit: int = 25
    ) -> Dict[str, Any]:
        """Paginate through comments on an issue if more context is needed."""
        key = self._resolve_issue_key(identifier)
        resp = self.jira.get_comments(key, start_at=start_at, max_results=min(limit, 50))
        return {
            "jira_key": key,
            "start_at": start_at,
            "total": resp.get("total", 0),
            "comments": [
                adf_to_text(c.get("body")).strip() for c in resp.get("comments", [])
            ],
        }
    def search_scoped_issues(self, keyword: str) -> List[Dict[str, str]]:
        """Search issues within the dataset scope by summary/text keyword."""
        safe_kw = keyword.replace('"', "").strip()
        jql = (
            f'project = "{self.project_key}" AND labels = "{self.dataset_label}" '
            f'AND text ~ "{safe_kw}"'
        )
        issues = self.jira.search_jql(jql, fields=["summary", "labels"], max_results=15)
        results = []
        for iss in issues:
            f = iss.get("fields", {})
            lbls = f.get("labels", [])
            src_id = next((l[7:] for l in lbls if l.startswith("source-")), iss["key"])
            results.append(
                {
                    "jira_key": iss["key"],
                    "source_id": src_id,
                    "summary": f.get("summary", ""),
                }
            )
        return results
    def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        t0 = time.time()
        try:
            if tool_name == "get_issue_details":
                result = self.get_issue_details(tool_input["identifier"])
            elif tool_name == "get_issue_comments_page":
                result = self.get_issue_comments_page(
                    tool_input["identifier"],
                    tool_input.get("start_at", 0),
                    tool_input.get("limit", 25),
                )
            elif tool_name == "search_scoped_issues":
                result = self.search_scoped_issues(tool_input["keyword"])
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            result = {"error": str(exc)}
        duration_ms = round((time.time() - t0) * 1000, 1)
        self.trace.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "duration_ms": duration_ms,
                "output_summary": str(result)[:600],
            }
        )
        return result
