from django.apps import AppConfig


class ItaliastadiaappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'italiastadiaapp'

    def ready(self):
        # Registers the runtime-compatibility system check. It runs on every
        # management command, so build.sh's `migrate` fails the DEPLOY rather
        # than shipping a site whose admin 500s on every page.
        from . import checks  # noqa: F401
