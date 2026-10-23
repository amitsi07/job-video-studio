import os, re, uuid, json, threading, subprocess, time
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/job-video-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
app = FastAPI(title="Job Video Studio")

class CreateRequest(BaseModel):
    url: HttpUrl
    title: str | None = None
    format: str = "both"  # landscape, vertical, or both

def safe_public_url(url: str):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only public HTTP/HTTPS URLs are allowed.")
    host = p.hostname.lower()
    blocked = ("localhost", "127.", "10.", "192.168.", "169.254.", "0.0.0.0")
    if host.endswith(".local") or any(host.startswith(x) for x in blocked):
        raise ValueError("Private/internal URLs are not allowed.")
    return url

def extract_article(url):
    safe_public_url(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobVideoStudio/1.0)"}
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    r.raise_for_status()
    if len(r.content) > 8_000_000:
        raise ValueError("Article page is too large to process.")
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form", "iframe"]):
        tag.decompose()
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:300]
    text = "\n".join(x.strip() for x in soup.stripped_strings)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title, text[:40000]

def simple_script(article_title, article_text, url, user_title=None):
    title = user_title or article_title or "भर्ती की पूरी जानकारी"
    lines = [x.strip() for x in article_text.splitlines() if len(x.strip()) > 2]
    keywords = {
        "पदों की जानकारी": ["vacancy", "रिक्त पद", "total posts", "पदों की संख्या", "posts"],
        "आवेदन की तारीख": ["last date", "अंतिम तिथि", "application last date", "important dates"],
        "योग्यता": ["qualification", "शैक्षणिक योग्यता", "educational qualification", "eligibility"],
        "आयु सीमा": ["age limit", "आयु सीमा", "minimum age", "maximum age"],
        "आवेदन शुल्क": ["application fee", "आवेदन शुल्क", "exam fee", "fee"],
        "चयन प्रक्रिया": ["selection process", "चयन प्रक्रिया", "written exam", "interview"],
        "आवेदन प्रक्रिया": ["how to apply", "आवेदन कैसे", "apply online", "application process"],
        "वेतन": ["salary", "pay scale", "वेतन", "सैलरी"],
    }
    sections = {}
    low_lines = [(x, x.lower()) for x in lines]
    for label, terms in keywords.items():
        sections[label] = [orig for orig, low in low_lines if any(term in low for term in terms)][:4]
    narration = [
        f"नमस्कार दोस्तों। आज हम बात करेंगे {title} के बारे में।",
        "आवेदन करने से पहले आधिकारिक नोटिफिकेशन जरूर पढ़ें।",
    ]
    for label in keywords:
        narration.append(label + " के बारे में उपलब्ध जानकारी देखते हैं।")
        found = sections.get(label, [])
        narration.extend(found[:2] if found else ["इस जानकारी की पुष्टि आधिकारिक नोटिफिकेशन से करनी होगी।"])
    narration.append("आवेदन करने से पहले तारीख, पात्रता और फीस आधिकारिक वेबसाइट पर दोबारा जांच लें।")
    return {"title": title, "sections": sections, "narration": "\n\n".join(narration), "source_url": url}

def run_cmd(args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-2500:])
    return p

def render_video(job_id):
    with LOCK:
        job = JOBS[job_id]
        job["status"] = "extracting"
    work = DATA_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    try:
        title, article = extract_article(job["url"])
        script = simple_script(title, article, job["url"], job.get("requested_title"))
        (work / "source.txt").write_text(article, encoding="utf-8")
        (work / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        (work / "script.txt").write_text(script["narration"], encoding="utf-8")
        with LOCK:
            JOBS[job_id].update({"status": "voice", "title": script["title"], "script": script["narration"], "sections": script["sections"]})

        tts_code = (
            "import asyncio, sys\n"
            "import edge_tts\n"
            "async def main():\n"
            "    text = open(sys.argv[1], encoding='utf-8').read()\n"
            "    communicate = edge_tts.Communicate(text, 'hi-IN-MadhurNeural', rate='+0%')\n"
            "    await communicate.save(sys.argv[2])\n"
            "asyncio.run(main())\n"
        )
        tts_file = work / "tts.py"
        tts_file.write_text(tts_code, encoding="utf-8")
        audio = work / "voice.mp3"
        run_cmd(["python", str(tts_file), str(work / "script.txt"), str(audio)])
        with LOCK:
            JOBS[job_id]["status"] = "rendering"

        font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        duration_text = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)]).stdout.strip()
        duration = max(15.0, float(duration_text or "60"))
        # Simple neutral title-card video with narration. Render only the format(s) selected by the user.
        all_formats = {"landscape": "1920x1080", "vertical": "1080x1920"}
        selected_formats = (list(all_formats.keys()) if job.get("format") == "both" else [job.get("format")])
        for fmt in selected_formats:
            size = all_formats[fmt]
            out = work / f"{fmt}.mp4"
            w, h = [int(x) for x in size.split("x")]
            ascii_title = re.sub(r"[^A-Za-z0-9 \-]", "", script["title"])[:60] or "Recruitment Information"
            draw = f"drawtext=fontfile={font}:text='{ascii_title}':fontcolor=white:fontsize={max(30,int(w*0.035))}:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=0x18243A@0.85:boxborderw=35"
            run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x102033:s={size}:r=25:d={duration}", "-i", str(audio),
                     "-vf", draw, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)])
        with LOCK:
            JOBS[job_id].update({
                "status": "review_required",
                "files": {fmt: f"/download/{job_id}/{fmt}" for fmt in selected_formats},
                "message": "Draft ready. Verify every recruitment fact against the official notification before publishing."
            })
    except Exception as e:
        with LOCK:
            JOBS[job_id].update({"status": "failed", "error": str(e)[:1500]})

@app.get("/", response_class=HTMLResponse)
def index():
    return (APP_DIR / "index.html").read_text(encoding="utf-8")

@app.post("/api/jobs")
def create_job(req: CreateRequest, background_tasks: BackgroundTasks):
    if req.format not in ("landscape", "vertical", "both"):
        raise HTTPException(400, "Format must be landscape, vertical, or both")
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"id": jid, "url": str(req.url), "requested_title": req.title, "format": req.format, "status": "queued", "created_at": time.time()}
    background_tasks.add_task(render_video, jid)
    return {"id": jid, "status": "queued"}

@app.get("/api/jobs")
def list_jobs():
    with LOCK:
        return sorted([{k:v for k,v in job.items() if k not in ("script",)} for job in JOBS.values()], key=lambda x: x.get("created_at", 0), reverse=True)

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "Job not found. Render Free restarts may clear in-memory demo jobs.")
        return JOBS[job_id]

@app.get("/download/{job_id}/{kind}")
def download(job_id: str, kind: str):
    if kind not in ("landscape", "vertical"):
        raise HTTPException(404, "Unknown format")
    path = DATA_DIR / job_id / f"{kind}.mp4"
    if not path.exists():
        raise HTTPException(404, "Video not ready or no longer available")
    return FileResponse(path, media_type="video/mp4", filename=f"{kind}.mp4")

@app.get("/health")
def health():
    return {"ok": True}
