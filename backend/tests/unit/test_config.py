"""Config normalization tests — both are deployment-correctness bugs waiting to happen if
regressed: a managed Postgres provider's connection string and Render's bare-hostname env var
interpolation must both come out usable without any manual per-deployment fixup.
"""

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql+asyncpg://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
    ],
)
def test_database_url_is_normalized_to_asyncpg_scheme(raw, expected):
    assert Settings(database_url=raw).database_url == expected


def test_cors_wildcard_stays_a_wildcard():
    assert Settings(cors_allowed_origins="*").cors_origin_list == ["*"]


def test_cors_bare_hostname_gets_https_scheme():
    settings = Settings(cors_allowed_origins="recoveryos-frontend.onrender.com")
    assert settings.cors_origin_list == ["https://recoveryos-frontend.onrender.com"]


def test_cors_already_schemed_origin_is_untouched():
    settings = Settings(cors_allowed_origins="https://example.com")
    assert settings.cors_origin_list == ["https://example.com"]


def test_cors_multiple_origins_comma_separated():
    settings = Settings(cors_allowed_origins="a.onrender.com, https://b.example.com")
    assert settings.cors_origin_list == ["https://a.onrender.com", "https://b.example.com"]
