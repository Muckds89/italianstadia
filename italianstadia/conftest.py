import pytest


@pytest.fixture(autouse=True)
def disable_cache(settings):
    """Replace the cache with a no-op backend for every test.

    cache_page() and other view-level caching would otherwise bleed state
    between tests that hit the same URL, causing spurious failures.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
