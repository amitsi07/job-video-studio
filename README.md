# Job Video Studio — starter prototype

Mobile-first starter dashboard for article URL → source text extraction → Hindi narration draft → Edge TTS → simple MP4 draft in landscape and vertical format.

## Important limitations
- This is a prototype, not production-ready automation.
- Job state is in memory. Render restarts can clear jobs.
- Output files are stored on ephemeral local disk and can be lost on restart.
- Article extraction does not reliably handle PDFs or JavaScript-heavy sites.
- The script is template-based, not verified AI research. It may omit or misclassify facts.
- The first renderer creates a simple title-card video with narration, not scene-by-scene official screenshots or complete subtitles.
- Edge TTS depends on an online service and may change or stop working.
- Verify all details against the official recruitment notification before publishing.
- This prototype does not auto-publish to YouTube or submit job applications.
- Never use uptime pings to bypass provider limits; use monitoring for availability only.

## Deploy on Render
1. Put these files in a GitHub repository.
2. In Render, create a new Blueprint and connect the repository; Render reads `render.yaml`.
3. Wait for build/deploy and open the generated Render URL.
4. Test with a public article URL. First startup may take time.
5. If deployment fails, inspect Render logs.

## Before real use
Add durable job state, object storage, a queue with retry/resume, official-source verification, robust URL/SSRF protection including DNS rebinding/redirect checks, proper subtitles, PDF parsing, scene-by-scene graphics, authentication and resource limits. Configure spending alerts before enabling any paid service.
