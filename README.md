# File Toolkit

A serverless Flask web app for image conversion/compression/rotation and
file-to-PDF generation, built to run on **Vercel's Python runtime**.

All file processing happens **100% in memory** (`io.BytesIO`) — nothing is
ever written to disk — because Vercel's serverless filesystem is ephemeral
and read-only outside of `/tmp`, which this app avoids entirely.

## Features

- **Image Tool** — convert between PNG / JPEG / WEBP, compress with an
  adjustable quality slider (10–100), and rotate by 0° / 90° / 180° / 270°.
- **File → PDF** — combine one or more images (`.png`, `.jpg`, `.webp`),
  `.txt` files, and `.docx` files into a single downloadable PDF.
- **PDF Rotator** — rotate every page of an uploaded PDF by 90° / 180° / 270°.
- Dark-mode, responsive Tailwind UI with drag-and-drop upload zones, async
  `fetch()` submissions, loading spinners, and automatic download triggers.
- **Client-side and server-side 4.5MB upload guardrails**, matching Vercel's
  serverless payload limit.


  # File Toolkit

> 🚀 **Live Demo:** [https://file-converter-azure-eta.vercel.app/](https://file-converter-azure-eta.vercel.app/)

## Project Structure

```
file-converter/
├── api/
│   └── index.py         # Flask backend & serverless entrypoint
├── templates/
│   └── index.html        # Tailwind CSS frontend UI
├── test_app.py            # Automated test suite (Flask test_client)
├── requirements.txt       # Python dependencies
├── vercel.json             # Vercel routing configuration
└── README.md
```

## Local Setup

1. **Create a virtual environment (optional but recommended):**

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the automated test suite:**

   ```bash
   python test_app.py
   ```

   This exercises every endpoint (`/api/health`, `/api/convert-image`,
   `/api/to-pdf`, `/api/rotate-pdf`) using Flask's built-in `test_client()` —
   no server needs to be running.

4. **Run the app locally:**

   ```bash
   python api/index.py
   ```

   Then open `http://127.0.0.1:5000` in your browser.

## API Endpoints

| Method | Path                  | Description                                                                 |
|--------|-----------------------|-------------------------------------------------------------------------------|
| GET    | `/`                   | Renders the frontend UI.                                                     |
| GET    | `/api/health`         | Returns `{"status": "ok"}`.                                                  |
| POST   | `/api/convert-image`  | Form fields: `file`, `format` (PNG/JPEG/WEBP), `quality` (10–100), `rotate` (0/90/180/270). Returns the converted image. |
| POST   | `/api/to-pdf`         | Form field `file` (one or more images/.txt/.docx). Returns a merged PDF.     |
| POST   | `/api/rotate-pdf`     | Form fields: `file` (a PDF), `angle` (90/180/270). Returns the rotated PDF.  |

## Deploying to Vercel

1. Install the Vercel CLI if you haven't already:

   ```bash
   npm install -g vercel
   ```

2. From the `file-converter/` directory, deploy:

   ```bash
   vercel
   ```

   Vercel will detect `vercel.json`, build `api/index.py` with the
   `@vercel/python` builder, and route all traffic (`/(.*)`) to it — including
   the `/` route, which Flask serves via `render_template`.

3. For production deployment:

   ```bash
   vercel --prod
   ```

### Notes on the Vercel environment

- **No disk writes.** Every conversion happens in an `io.BytesIO()` buffer
  and is streamed back via Flask's `send_file()`. This is required because
  Vercel functions run on a read-only filesystem outside of `/tmp`.
- **4.5MB payload limit.** Vercel serverless functions cap request/response
  bodies at 4.5MB. The frontend blocks oversized files client-side before
  they're ever uploaded, and the backend also enforces
  `MAX_CONTENT_LENGTH` and returns a friendly `413` JSON error as a second
  line of defense.
- **Cold starts.** Pillow/reportlab/python-docx add some cold-start latency
  on the first request after a period of inactivity — this is normal for
  serverless Python functions.

## Tech Stack

- **Backend:** Flask 3, Pillow, pypdf, python-docx, reportlab
- **Frontend:** Tailwind CSS (CDN), vanilla JavaScript (no build step)
- **Deployment:** Vercel `@vercel/python` serverless runtime
