"""Worker-side HTTP client for chunk operations through Orca.

Workers do not talk to Redis directly in the MVP architecture. They talk
to Orca, and Orca owns the Redis queue backend internally.

Expected Orca endpoints:

  GET  /chunks/next?job_id=...&chain_id=...
  POST /chunks/{chunk_id}/renew
  POST /chunks/{chunk_id}/complete
  POST /chunks/{chunk_id}/fail

This keeps Redis hidden from worker networking and lets Orca swap queue
backends later without changing worker code.
"""

from __future__ import annotations

from typing import Any

import httpx

from tandemn_user_data.core import ChunkLease, ChunkProgress

DEFAULT_WORKER_AUTH_HEADER = "X-Tandemn-Worker-Token"


class OrcaChunkClient:
    """Worker-facing chunk API client.

    This is data-plane code: workers import it to pull/renew/complete/fail
    chunks by calling Orca. It does not import tandemn_system_data.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        auth_header: str = DEFAULT_WORKER_AUTH_HEADER,
        timeout: float = 10.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        self._headers = {auth_header: token} if token else {}
        self._timeout = timeout

    def pull_chunk(self, job_id: str, chain_id: str) -> ChunkLease | None:
        """Ask Orca for the next chunk. Returns None when no chunk is available."""
        resp = httpx.get(
            f"{self._base_url}/chunks/next",
            params={"job_id": job_id, "chain_id": chain_id},
            headers=self._headers,
            timeout=self._timeout,
        )
        if resp.status_code == 204:
            return None
        self._raise_for_known_errors(resp)
        return ChunkLease.model_validate(resp.json())

    def renew_lease(self, job_id: str, chunk_id: str, chain_id: str) -> bool:
        resp = httpx.post(
            f"{self._base_url}/chunks/{chunk_id}/renew",
            json={"job_id": job_id, "chain_id": chain_id},
            headers=self._headers,
            timeout=self._timeout,
        )
        if resp.status_code == 409:
            return False
        self._raise_for_known_errors(resp)
        body = resp.json()
        return bool(body.get("renewed", True))

    def complete_chunk(self, job_id: str, chunk_id: str, chain_id: str) -> ChunkProgress:
        resp = httpx.post(
            f"{self._base_url}/chunks/{chunk_id}/complete",
            json={"job_id": job_id, "chain_id": chain_id},
            headers=self._headers,
            timeout=self._timeout,
        )
        self._raise_for_known_errors(resp)
        return ChunkProgress.model_validate(resp.json())

    def fail_chunk(
        self,
        job_id: str,
        chunk_id: str,
        chain_id: str,
        reason_code: str,
    ) -> ChunkProgress:
        resp = httpx.post(
            f"{self._base_url}/chunks/{chunk_id}/fail",
            json={"job_id": job_id, "chain_id": chain_id, "reason_code": reason_code},
            headers=self._headers,
            timeout=self._timeout,
        )
        self._raise_for_known_errors(resp)
        return ChunkProgress.model_validate(resp.json())

    @staticmethod
    def _raise_for_known_errors(resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise PermissionError("worker token not accepted by Orca")
        if resp.status_code == 403:
            raise PermissionError("worker is not allowed to operate on this chunk")
        if resp.status_code == 404:
            raise KeyError("chunk or job not found")
        if resp.status_code >= 400:
            detail: Any
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            raise RuntimeError(f"Orca chunk API returned {resp.status_code}: {detail}")
