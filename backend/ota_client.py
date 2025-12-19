from typing import Tuple, Dict, Any, List

from .config import OPEN_TERMS_BASE_URL


class OpenTermsClient:
    """
    Placeholder client for Open Terms Archive (or similar).
    For now this is a stub so that the API code imports cleanly.

    Later, you can implement real HTTP calls using httpx:
      - list_versions(service_id, doc_type)
      - fetch_latest_two_versions(...)
      - fetch_version_content(...)
    """

    def __init__(self, base_url: str = OPEN_TERMS_BASE_URL, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_versions(
        self,
        service_id: str,
        doc_type: str,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "OpenTermsClient.list_versions is not implemented yet. "
            "You can implement this once you decide the real OTA endpoint."
        )

    async def fetch_latest_two_versions(
        self,
        service_id: str,
        doc_type: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raise NotImplementedError(
            "OpenTermsClient.fetch_latest_two_versions is not implemented yet."
        )

    async def fetch_version_content(
        self,
        service_id: str,
        doc_type: str,
        version_id: str,
    ) -> str:
        raise NotImplementedError(
            "OpenTermsClient.fetch_version_content is not implemented yet."
        )
