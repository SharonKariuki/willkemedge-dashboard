import io
from django.template.loader import get_template
from xhtml2pdf import pisa

def render_to_pdf(template_src, context_dict={}):
    """
    Renders an HTML template into a PDF byte string using xhtml2pdf.
    """
    template = get_template(template_src)
    html = template.render(context_dict)
    result = io.BytesIO()
    
    # Create the PDF
    pdf = pisa.pisaDocument(
        io.BytesIO(html.encode("UTF-8")), 
        result,
        encoding="UTF-8"
    )
    
    if not pdf.err:
        return result.getvalue()
    return None
