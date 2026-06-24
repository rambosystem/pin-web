from __future__ import annotations

from typing import Any

from lib.atlassian import jira_api_v3_url
from lib.http import request_json


def get_remotelinks(base_url: str, auth: str, issue_key: str) -> list[dict[str, Any]]:
    url = jira_api_v3_url(base_url, f"/issue/{issue_key}/remotelink")
    data = request_json(
        url,
        headers={"Accept": "application/json", "Authorization": f"Basic {auth}"},
        insecure_env_var="JIRA_INSECURE_SSL",
    )
    return data if isinstance(data, list) else []


def delete_remotelink_by_link_id(base_url: str, auth: str, issue_key: str, link_id: int) -> None:
    url = jira_api_v3_url(base_url, f"/issue/{issue_key}/remotelink/{link_id}")
    request_json(
        url,
        method="DELETE",
        headers={"Accept": "application/json", "Authorization": f"Basic {auth}"},
        insecure_env_var="JIRA_INSECURE_SSL",
    )


def delete_remotelink_for_confluence_page(
    base_url: str,
    auth: str,
    issue_key: str,
    confluence_page_id: str | int,
) -> bool:
    page_id_str = str(confluence_page_id)
    links = get_remotelinks(base_url, auth, issue_key)
    for link in links:
        app = link.get("application") or {}
        if app.get("type") != "com.atlassian.confluence":
            continue
        global_id = link.get("globalId") or ""
        obj = link.get("object") or {}
        obj_url = (obj.get("url") or "") or ""
        if page_id_str in global_id or page_id_str in obj_url:
            link_id = link.get("id")
            if link_id is not None:
                delete_remotelink_by_link_id(base_url, auth, issue_key, int(link_id))
                return True
    return False
