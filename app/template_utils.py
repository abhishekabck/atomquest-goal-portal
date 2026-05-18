"""Compatibility shim: supports both old and new starlette TemplateResponse API.

Also injects Flask-compatible get_flashed_messages() as a no-op global so
templates that use it continue to work without Flask.
"""
from starlette.templating import Jinja2Templates as _Base


def _get_flashed_messages(with_categories=False):
    """No-op stub; FastAPI uses query-param messages instead of flash."""
    return []


class Templates(_Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Inject get_flashed_messages so base.html doesn't raise UndefinedError
        self.env.globals["get_flashed_messages"] = _get_flashed_messages

    def TemplateResponse(self, name_or_request, context_or_name=None, context=None, **kwargs):
        if isinstance(name_or_request, str):
            # Old-style: TemplateResponse("name.html", {"request": req, ...})
            name = name_or_request
            ctx = context_or_name if isinstance(context_or_name, dict) else (context or {})
            request = ctx.get("request")
            return super().TemplateResponse(request, name, ctx, **kwargs)
        # New-style: TemplateResponse(request, "name.html", context)
        return super().TemplateResponse(name_or_request, context_or_name, context or {}, **kwargs)
