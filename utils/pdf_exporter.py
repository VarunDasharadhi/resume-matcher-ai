from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

def export_analysis_to_pdf(content, filename="match_result.pdf"):
    output_path = os.path.join("uploads", filename)
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    lines = content.split("\n")
    y = height - 40
    for line in lines:
        if y < 40:  # new page if needed
            c.showPage()
            y = height - 40
        c.drawString(40, y, line[:120])  # wrap long lines
        y -= 18

    c.save()
    return output_path

def export_cover_letter_to_pdf(content, filename="cover_letter.pdf"):
    output_path = os.path.join("uploads", filename)
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    lines = content.split("\n")
    y = height - 40
    for line in lines:
        if y < 40:
            c.showPage()
            y = height - 40
        c.drawString(40, y, line[:120])
        y -= 18

    c.save()
    return output_path
