from django.conf import settings


def adsense(request):
    return {
        "adsense_client": settings.GOOGLE_ADSENSE_CLIENT,
        "adsense_slot": settings.GOOGLE_ADSENSE_SLOT,
    }
