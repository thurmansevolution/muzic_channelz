#!/usr/bin/env python3
"""Generate UPDATE_NOTES.pdf in project root from the same content as UPDATE_NOTES.md.
Requires: pip install reportlab
Run from project root: python scripts/generate_update_pdf.py
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "UPDATE_NOTES.pdf"


def add_para(doc, style, text):
    doc.append(Paragraph(text.replace("\n", "<br/>"), style))


def main():
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=inch * 0.75,
        rightMargin=inch * 0.75,
        topMargin=inch * 0.75,
        bottomMargin=inch * 0.75,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=9, textColor="gray"))
    story = []

    story.append(Paragraph("muzic channelz — Update Notes", styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "Summary of changes and how to update (for users who already have the project from GitHub).",
        styles["Small"],
    ))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("What’s New and Changed", styles["Heading1"]))
    story.append(Spacer(1, 0.15 * inch))

    # 1. Backup & Restore
    story.append(Paragraph("1. Backup &amp; Restore — Full Restore Including Logos", styles["Heading2"]))
    for item in [
        "Backup export now includes <b>custom channel logos</b> (PNG files) in addition to admin state, channels, FFmpeg profiles, Azuracast stations, and custom background images.",
        "Backup format version is <b>2</b> (older v1 backups still restore; logos are optional).",
        "Restore writes restored channel logos to data/channel_logos/ so all user-specific data comes back.",
        "Administration UI backup/restore section describes that custom channel logos are included; restore confirmation mentions logos.",
    ]:
        story.append(Paragraph(f"• {item}", styles["Normal"]))
    story.append(Paragraph("<i>Files: app/routers/admin.py, frontend/src/views/Administration.jsx</i>", styles["Small"]))
    story.append(Spacer(1, 0.2 * inch))

    # 2. Plex
    story.append(Paragraph("2. Plex / Live TV — Channel Logos in the Guide", styles["Heading2"]))
    for item in [
        "XMLTV guide (/guide.xml) now uses the <b>same base URL as the request</b> for channel icon URLs, so Plex can fetch logos from the same origin as the guide.",
        "Request is passed from the HDHomeRun guide handler so icon URLs use the correct host/port.",
        "Channel icons remain URL-based in the XMLTV for compatibility with Plex.",
    ]:
        story.append(Paragraph(f"• {item}", styles["Normal"]))
    story.append(Paragraph("<i>Files: app/routers/channels.py, app/routers/hdhr.py</i>", styles["Small"]))
    story.append(Spacer(1, 0.2 * inch))

    # 3. Logo endpoint
    story.append(Paragraph("3. Channel Logo Endpoint — “No Logo Available” Fixed", styles["Heading2"]))
    for item in [
        "Default logo is now resolved from two locations: frontend/public/logo.png, then app/static/default-art.png.",
        "Path bug fix: stock logo path was computed from the wrong base directory; it now uses the project root.",
        "app/static/default-art.png was added to the repo so the default logo is always present.",
        "Root /logo.png uses the same dual-path logic.",
    ]:
        story.append(Paragraph(f"• {item}", styles["Normal"]))
    story.append(Paragraph("<i>Files: app/routers/channels.py, app/main.py; new file: app/static/default-art.png</i>", styles["Small"]))
    story.append(Spacer(1, 0.2 * inch))

    # 4. Startup
    story.append(Paragraph("4. Startup / Web UI — Reliability Fixes", styles["Heading2"]))
    for item in [
        "Guide endpoint now takes a required Request parameter to avoid a FastAPI startup error.",
        "Web UI: app only serves the SPA when frontend/dist/index.html exists and only mounts /assets when frontend/dist/assets exists.",
    ]:
        story.append(Paragraph(f"• {item}", styles["Normal"]))
    story.append(Paragraph("<i>Files: app/routers/channels.py, app/main.py</i>", styles["Small"]))
    story.append(Spacer(1, 0.3 * inch))

    # Update instructions
    story.append(Paragraph("Update Instructions", styles["Heading1"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("If you run from Docker", styles["Heading2"]))
    story.append(Paragraph("1. Pull the latest code: cd muzic_channelz &amp;&amp; git pull", styles["Normal"]))
    story.append(Paragraph("2. Rebuild and restart: docker compose build --no-cache then docker compose up -d", styles["Normal"]))
    story.append(Paragraph("3. (Optional) Refresh the EPG in Plex so it refetches the guide and channel logos.", styles["Normal"]))
    story.append(Paragraph("Your data (channels, backgrounds, logos) is in the Docker volume and is not overwritten.", styles["Small"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("If you run on Linux / Debian (from source)", styles["Heading2"]))
    story.append(Paragraph("1. Pull the latest code: cd muzic_channelz &amp;&amp; git pull", styles["Normal"]))
    story.append(Paragraph("2. Update deps and rebuild frontend: source .venv/bin/activate, pip install -r requirements.txt, cd frontend &amp;&amp; npm install &amp;&amp; npm run build &amp;&amp; cd ..", styles["Normal"]))
    story.append(Paragraph("3. Restart the app: ./manage.sh restart or restart uvicorn manually.", styles["Normal"]))
    story.append(Paragraph("4. (Optional) Refresh the EPG in Plex.", styles["Normal"]))
    story.append(Paragraph("Your data/ folder is unchanged by the update.", styles["Small"]))
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph("Quick Checklist for Your Group Announcement", styles["Heading1"]))
    for item in [
        "Backup/restore now includes <b>custom channel logos</b> for full restore.",
        "Plex (and other Live TV) channel logos should display when the guide is refreshed.",
        "“No logo available” when opening logo URLs is fixed.",
        "Server startup is fixed with the updated code.",
        "Update: pull latest, rebuild (Docker) or rebuild frontend + restart (Linux), then optionally refresh the EPG in Plex.",
    ]:
        story.append(Paragraph(f"• {item}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("<i>Generated for the muzic channelz update.</i>", styles["Small"]))

    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
