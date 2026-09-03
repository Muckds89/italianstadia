"""
System checks, run explicitly by build.sh so an incompatible runtime fails the DEPLOY
instead of shipping a site whose admin 500s on every page.

build.sh calls `manage.py check` for this. It cannot rely on `migrate`: that command
sets requires_system_checks = [] and runs NONE of them, so this file was originally
described as gating the deploy while in fact never running during one.

WHY THIS FILE EXISTS. The project had no Python version pin. Render moved its
default runtime to Python 3.14, and Django 5.1 cannot copy a template Context on
3.14: BaseContext.__copy__ does `copy(super())`, which there yields an object
with no __dict__, so the next line `duplicate.dicts = ...` raises AttributeError.
Every Django admin page returned 500 while the public site kept serving happily,
because only the admin renders inclusion tags that call Context.new(). It took a
production traceback to find, since nothing anywhere said "this Django cannot run
on this Python".

WHY THIS TESTS BEHAVIOUR AND NOT A VERSION NUMBER. The obvious check — compare
sys.version_info against Django's supported-Python classifiers — is wrong in both
directions. Django 5.1.2's own metadata stops at 3.12, yet it runs fine on the
3.13 this project develops on, so a classifier check would fail on the
developer's own machine. And the next such breakage may not be a Python bump at
all. Exercising the operation that actually broke costs microseconds and cannot
be wrong about whether it works.
"""
import sys
from copy import copy

import django
from django.core.checks import Error, register


@register()
def template_context_is_copyable(app_configs, **kwargs):
    """Context.new() must work, or every admin page 500s.

    This is the exact call the admin makes on every changelist, via
    InclusionAdminNode.render -> Context.new() -> copy(self).
    """
    from django.template.context import Context

    try:
        ctx = Context({"probe": 1})
        ctx.new({"probe": 2})
        copy(ctx)
    except Exception as exc:
        py = ".".join(str(n) for n in sys.version_info[:3])
        return [Error(
            f"Django {django.get_version()} cannot copy a template Context on "
            f"Python {py}: {type(exc).__name__}: {exc}",
            hint=(
                "The Django admin is entirely broken on this combination — every "
                "page returns 500 — while the public site keeps working, so this "
                "will not be obvious from the outside. Pin the runtime "
                "(.python-version and PYTHON_VERSION in render.yaml) or upgrade "
                "Django to a release supporting this Python. Do not silence this "
                "check: it is reporting a real, reproducible failure."
            ),
            id="italiastadiaapp.E001",
        )]
    return []
