"""Serve only page assets and synthetic bridge data for visual inspection."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "pages" / "logs"), **kwargs)

    def do_GET(self):
        if self.path == "/api/plugin/page/bridge-sdk.js":
            script = (
                (ROOT / "tests" / "page_fixture.mjs")
                .read_text(encoding="utf-8-sig")
                .replace("export ", "")
            )
            script += "\nwindow.AstrBotPluginPage={ready:async()=>{},apiGet:async path=>fixtureReply(path),apiPost:async(path,body)=>fixtureReply(path,body)};"
            payload = script.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8374), PreviewHandler).serve_forever()
