"""
Generate PDFs from the MkDocs built site using Playwright headless Chromium.

Run this AFTER `mkdocs build` and BEFORE deploying to gh-pages.
PDFs are saved to site/assets/pdfs/ and will be served as direct downloads.

Usage:
    python landnotev3/scripts/generate_pdfs.py
    python landnotev3/scripts/generate_pdfs.py --site-dir /path/to/site
"""
import asyncio
import subprocess
import time
import sys
import argparse
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Generate PDFs from MkDocs built site")
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=Path(__file__).parent.parent / "site_src" / "site",
        help="Path to the built MkDocs site directory (default: site_src/site)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the temporary local HTTP server (default: 8765)",
    )
    return parser.parse_args()


async def generate_pdfs(site_dir: Path, port: int):
    from playwright.async_api import async_playwright

    pdf_dir = site_dir / "assets" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    review_dir = site_dir / "review"
    if not review_dir.exists():
        print(f"[ERROR] Review directory not found: {review_dir}")
        print("Make sure `mkdocs build` has been run first.")
        sys.exit(1)

    # Collect all rendered review pages (subdirs with index.html)
    tags = sorted(
        item.name
        for item in review_dir.iterdir()
        if item.is_dir() and (item / "index.html").exists()
    )

    if not tags:
        print("[WARN] No review pages found. Nothing to convert.")
        return

    print(f"Found {len(tags)} review pages to convert to PDF")

    # Start a local HTTP server so Chromium can load CSS/JS correctly
    base_url = f"http://localhost:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(site_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give server time to start
    time.sleep(3)

    # CSS injected into each page before PDF export:
    # - hide site chrome (nav, sidebar, footer, study tools bar)
    # - expand content to full width
    PRINT_CSS = """
        .md-header, .md-sidebar--primary, .md-sidebar--secondary,
        .md-footer, .md-tabs, #study-tools-container,
        .md-source, .md-top, .md-search {
            display: none !important;
        }
        .md-grid { max-width: 100% !important; }
        .md-content { margin: 0 !important; max-width: 100% !important; }
        .md-main__inner { margin-top: 0 !important; padding: 0 !important; }
        .md-content__inner { padding: 1rem 0 !important; }
        body { font-size: 14px !important; }
        h1 { font-size: 1.6rem !important; }
        h2 { font-size: 1.3rem !important; }
        h3 { font-size: 1.1rem !important; }
    """

    success_count = 0
    fail_count = 0

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            for tag_name in tags:
                url = f"{base_url}/review/{tag_name}/"
                pdf_path = pdf_dir / f"{tag_name}.pdf"

                # "all" contains every article — allow extra time
                timeout_ms = 180_000 if tag_name == "all" else 60_000

                try:
                    page = await browser.new_page(viewport={"width": 1200, "height": 900})
                    await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    await page.add_style_tag(content=PRINT_CSS)

                    await page.pdf(
                        path=str(pdf_path),
                        format="A4",
                        margin={
                            "top": "15mm",
                            "bottom": "15mm",
                            "left": "20mm",
                            "right": "20mm",
                        },
                        print_background=False,
                        display_header_footer=False,
                    )

                    size_kb = pdf_path.stat().st_size // 1024
                    print(f"  ✓ {tag_name}.pdf  ({size_kb} KB)")
                    success_count += 1
                    await page.close()

                except Exception as exc:
                    print(f"  ✗ {tag_name}: {exc}")
                    fail_count += 1

            await browser.close()

    finally:
        server.terminate()

    print(f"\nDone: {success_count} succeeded, {fail_count} failed")
    print(f"PDFs saved to: {pdf_dir}")

    if fail_count > 0:
        sys.exit(1)


def main():
    args = parse_args()
    if not args.site_dir.exists():
        print(f"[ERROR] Site directory not found: {args.site_dir}")
        print("Run `mkdocs build` first.")
        sys.exit(1)
    asyncio.run(generate_pdfs(args.site_dir, args.port))


if __name__ == "__main__":
    main()
