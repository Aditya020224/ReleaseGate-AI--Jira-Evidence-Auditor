from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
import requests
from requests.auth import HTTPBasicAuth
def text_to_adf(text: str) -> Dict[str, Any]:
    """Convert plain text into Atlassian Document Format (ADF) for Jira REST API v3."""
    paragraphs = []
    for line in (text or "").split("\n"):
        if line.strip():
            paragraphs.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": line}],
                }
            )
        else:
            paragraphs.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": paragraphs}
def adf_to_text(node: Any) -> str:
    """Recursively extract plain text from Jira ADF JSON structures."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(item) for item in node)
    if isinstance(node, dict):
        node_type = node.get("type", "")
        if node_type == "text":
            return node.get("text", "")
        if node_type == "hardBreak":
            return "\n"
        children_text = "".join(adf_to_text(child) for child in node.get("content", []))
        if node_type in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
            return children_text + "\n"
        return children_text
    return ""
class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(email, api_token)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        max_retries = 5
        for attempt in range(max_retries):
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(retry_after, 15))
                continue
            if resp.status_code >= 500 and attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            if not resp.ok:
                raise RuntimeError(
                    f"Jira API {method} {path} failed ({resp.status_code}): {resp.text[:500]}"
                )
            if resp.status_code == 204 or not resp.text:
                return {}
            return resp.json()
        raise RuntimeError(f"Jira API {method} {path} exceeded max retries.")
    def search_jql(
        self, jql: str, fields: Optional[List[str]] = None, max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Paginate through all issues matching a JQL query using /rest/api/3/search/jql."""
        fields = fields or ["summary", "description", "status", "labels", "issuelinks"]
        all_issues: List[Dict[str, Any]] = []
        next_page_token: Optional[str] = None
        while True:
            payload: Dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": fields,
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token
            data = self._request("POST", "/rest/api/3/search/jql", json=payload)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break
        return all_issues
    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": "summary,description,status,labels,issuelinks"},
        )
    def get_comments(
        self, issue_key: str, start_at: int = 0, max_results: int = 100
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        )
    def create_issue(
        self,
        project_key: str,
        summary: str,
        description_text: str,
        labels: List[str],
        issue_type: str = "Task",
    ) -> str:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary[:254],
                "description": text_to_adf(description_text),
                "issuetype": {"name": issue_type},
                "labels": labels,
            }
        }
        data = self._request("POST", "/rest/api/3/issue", json=payload)
        return data["key"]
    def add_comment(self, issue_key: str, comment_text: str) -> None:
        payload = {"body": text_to_adf(comment_text)}
        self._request("POST", f"/rest/api/3/issue/{issue_key}/comment", json=payload)
    def get_link_type_name(self) -> str:
        data = self._request("GET", "/rest/api/3/issueLinkType")
        link_types = data.get("issueLinkTypes", [])
        for lt in link_types:
            if lt.get("name", "").lower() == "relates":
                return lt["name"]
        if link_types:
            return link_types[0]["name"]
        raise RuntimeError("No issue link types found in Jira instance.")
    def create_issue_link(
        self, inward_key: str, outward_key: str, link_type: str = "Relates"
    ) -> None:
        payload = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_key},
            "outwardIssue": {"key": outward_key},
        }
        self._request("POST", "/rest/api/3/issueLink", json=payload)