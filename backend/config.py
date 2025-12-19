from typing import Dict, List, TypedDict


class PolicyInfo(TypedDict):
    doc_type: str
    description: str


class ServiceInfo(TypedDict):
    id: str
    name: str
    provider: str
    policies: List[PolicyInfo]


# In a real deployment, you might load this from a DB or config file.
SERVICES: Dict[str, ServiceInfo] = {
    "reddit": {
        "id": "reddit",
        "name": "Reddit",
        "provider": "OpenTermsArchive",
        "policies": [
            {"doc_type": "privacy_policy", "description": "Reddit Privacy Policy"},
            {"doc_type": "terms_of_service", "description": "Reddit User Agreement"},
        ],
    },
    "instagram": {
        "id": "instagram",
        "name": "Instagram",
        "provider": "OpenTermsArchive",
        "policies": [
            {"doc_type": "privacy_policy", "description": "Instagram Privacy Policy"},
        ],
    },
    # Add more later if you want...
}

# Placeholder for Open Terms Archive base URL.
# You will customise this once you decide the exact OTA endpoint.
OPEN_TERMS_BASE_URL = "https://opentermsarchive.example/api"
