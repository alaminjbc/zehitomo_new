from __future__ import annotations

from pydantic import BaseModel, Field


class Contractor(BaseModel):
    contractor_name: str = Field(description="Name at top of chat box")
    location: str = Field(description="Location from details/map")
    phone_number: str = Field(default="", description="Phone or empty")
    email: str = Field(default="", description="Email or empty")
    url_to_access_to_contractor: str = Field(
        default="",
        description=(
            "Zehitomo public profile URL "
            "(https://www.zehitomo.com/profile/...) found by Google-searching "
            "contractor_name + ' ゼヒトモ', opening the top 1-2 result links, "
            "and verifying the final page URL"
        ),
    )
    other_contractor_website_url: str = Field(
        default="",
        description=(
            "Non-Zehitomo website/URL taken only from contractor chat "
            "messages (empty if none)"
        ),
    )


class ScrapingResult(BaseModel):
    postal_code: str
    service: str
    combination_id: str = ""
    contractors: list[Contractor]
