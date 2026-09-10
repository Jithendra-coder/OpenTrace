"""M0 health and version endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from opentrace import __version__
from opentrace.config.settings import get_settings

router = APIRouter()


class ServiceStatus(BaseModel):
    status: str
    service: str


class ServiceVersion(BaseModel):
    service: str
    version: str


@router.get("/health", response_model=ServiceStatus)
def health() -> ServiceStatus:
    """Return the availability of the application shell only."""
    return ServiceStatus(status="ok", service=get_settings().service_name)


@router.get("/version", response_model=ServiceVersion)
def version() -> ServiceVersion:
    """Return the single package-authoritative application version."""
    return ServiceVersion(service=get_settings().service_name, version=__version__)

