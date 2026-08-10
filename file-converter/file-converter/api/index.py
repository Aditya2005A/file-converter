"""
File Converter / Image Toolkit / PDF Toolkit
Flask backend designed for serverless deployment on Vercel.

CRITICAL DESIGN CONSTRAINTS:
- Vercel's filesystem is ephemeral and read-only (except /tmp, which we avoid
  entirely). Every file operation below happens in memory using io.BytesIO.
- Vercel's serverless functions enforce a 4.5MB request/response payload
  limit. The frontend performs a client-side check to block oversized
  uploads before they are ever sent, and the backend also enforces a hard
  cap via MAX_CONTENT_LENGTH as a defense-in-depth measure.
"""

import io
import os

from flask import Flask, request, jsonify, send_file, render_template
from PIL import Image
from pypdf import PdfReader, PdfWriter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

app = Flask(__name__, template_folder="../templates")

# Defense-in-depth: reject anything bigger than the Vercel payload guardrail
# server-side too, even though the frontend already blocks it client-side.
MAX_UPLOAD_BYTES = int(4.5 * 1024 * 1024)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + (256 * 1024)  # small buffer for multipart overhead

ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "JPG", "WEBP"}
ALLOWED_ROTATIONS = {0, 90, 180, 270}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message, status=400):
    return jsonify({"error": message}), status


def _normalize_format(fmt: str) -> str:
    fmt = (fmt or "PNG").strip().upper()
    if fmt == "JPG":
        fmt = "JPEG"
    return fmt


def _pil_save_kwargs(fmt: str, quality: int) -> dict:
    kwargs = {}
    if fmt in ("JPEG", "WEBP"):
        kwargs["quality"] = quality
    if fmt == "JPEG":
        kwargs["optimize"] = True
    return kwargs


def _text_to_pdf_bytes(text: str) -> io.BytesIO:
    """Render plain text onto a PDF using reportlab, paginating as needed."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch
    line_height = 14
    max_width = width - 2 * margin
    x = margin
    y = height - margin

    c.setFont("Helvetica", 11)

    # Wrap long lines manually since reportlab does not auto-wrap text.
    def wrap_line(line, font_name, font_size):
        if not line:
            return [""]
        words = line.split(" ")
        wrapped = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if c.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)
        return wrapped or [""]

    for raw_line in text.splitlines() or [""]:
        for line in wrap_line(raw_line, "Helvetica", 11):
            if y < margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - margin
            c.drawString(x, y, line)
            y -= line_height

    c.save()
    buffer.seek(0)
    return buffer


def _docx_to_pdf_bytes(file_stream) -> io.BytesIO:
    """Extract text from a .docx file and render it onto a PDF."""
    document = Document(file_stream)
    paragraphs = [p.text for p in document.paragraphs]
    text = "\n".join(paragraphs)
    return _text_to_pdf_bytes(text)


def _image_to_pdf_bytes(file_stream) -> io.BytesIO:
    """Convert a single image into a single-page PDF sized to the image."""
    img = Image.open(file_stream)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="PDF")
    buffer.seek(0)
    return buffer


def _merge_pdfs(pdf_buffers) -> io.BytesIO:
    writer = PdfWriter()
    for buf in pdf_buffers:
        buf.seek(0)
        reader = PdfReader(buf)
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/convert-image", methods=["POST"])
def convert_image():
    if "file" not in request.files:
        return _error("No file part named 'file' in the request.")

    file = request.files["file"]
    if file.filename == "":
        return _error("No file selected.")

    target_format = _normalize_format(request.form.get("format", "PNG"))
    if target_format not in ALLOWED_IMAGE_FORMATS:
        return _error(f"Unsupported format '{target_format}'. Use PNG, JPEG, or WEBP.")

    try:
        quality = int(request.form.get("quality", 90))
    except (TypeError, ValueError):
        return _error("Quality must be an integer between 10 and 100.")
    quality = max(10, min(100, quality))

    try:
        rotate = int(request.form.get("rotate", 0))
    except (TypeError, ValueError):
        return _error("Rotate must be one of 0, 90, 180, 270.")
    if rotate not in ALLOWED_ROTATIONS:
        return _error("Rotate must be one of 0, 90, 180, 270.")

    try:
        img = Image.open(file.stream)
        img.load()
    except Exception:
        return _error("Uploaded file is not a valid image.")

    if rotate:
        # PIL rotate() is counter-clockwise; expand=True keeps full canvas.
        img = img.rotate(-rotate, expand=True)

    if target_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif target_format == "PNG" and img.mode == "P":
        img = img.convert("RGBA")

    out_buffer = io.BytesIO()
    try:
        img.save(out_buffer, format=target_format, **_pil_save_kwargs(target_format, quality))
    except Exception as exc:
        return _error(f"Failed to convert image: {exc}")
    out_buffer.seek(0)

    ext = "jpg" if target_format == "JPEG" else target_format.lower()
    mimetype = f"image/{'jpeg' if target_format == 'JPEG' else target_format.lower()}"

    return send_file(
        out_buffer,
        mimetype=mimetype,
        as_attachment=True,
        download_name=f"converted.{ext}",
    )


@app.route("/api/to-pdf", methods=["POST"])
def to_pdf():
    files = request.files.getlist("file")
    if not files:
        single = request.files.get("file")
        files = [single] if single else []

    if not files or all(f.filename == "" for f in files):
        return _error("No files provided. Attach one or more files under the 'file' field.")

    pdf_buffers = []
    for f in files:
        if f.filename == "":
            continue
        filename = f.filename.lower()
        try:
            if filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
                pdf_buffers.append(_image_to_pdf_bytes(f.stream))
            elif filename.endswith(".txt"):
                text = f.stream.read().decode("utf-8", errors="replace")
                pdf_buffers.append(_text_to_pdf_bytes(text))
            elif filename.endswith(".docx"):
                pdf_buffers.append(_docx_to_pdf_bytes(f.stream))
            else:
                return _error(
                    f"Unsupported file type for '{f.filename}'. "
                    "Allowed: .png, .jpg, .jpeg, .webp, .txt, .docx"
                )
        except Exception as exc:
            return _error(f"Failed to process '{f.filename}': {exc}")

    if not pdf_buffers:
        return _error("No valid files were provided.")

    try:
        merged = _merge_pdfs(pdf_buffers)
    except Exception as exc:
        return _error(f"Failed to assemble PDF: {exc}")

    return send_file(
        merged,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="converted.pdf",
    )


@app.route("/api/rotate-pdf", methods=["POST"])
def rotate_pdf():
    if "file" not in request.files:
        return _error("No file part named 'file' in the request.")

    file = request.files["file"]
    if file.filename == "":
        return _error("No file selected.")

    try:
        angle = int(request.form.get("angle", 90))
    except (TypeError, ValueError):
        return _error("Angle must be one of 90, 180, 270.")
    if angle not in (90, 180, 270):
        return _error("Angle must be one of 90, 180, 270.")

    try:
        reader = PdfReader(file.stream)
    except Exception:
        return _error("Uploaded file is not a valid PDF.")

    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)

    out_buffer = io.BytesIO()
    writer.write(out_buffer)
    out_buffer.seek(0)

    return send_file(
        out_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="rotated.pdf",
    )


@app.errorhandler(413)
def too_large(_e):
    return _error(
        f"File too large. Maximum allowed upload size is {MAX_UPLOAD_BYTES / (1024 * 1024):.1f}MB.",
        status=413,
    )


# Vercel's @vercel/python runtime looks for a module-level `app` object.
app = app


if __name__ == "__main__":
    app.run(debug=True)
