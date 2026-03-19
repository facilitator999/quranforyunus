"""Fast local server: threaded HTTP + Range support for MP3 seeking."""
import io
import os
import re
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Sends Accept-Ranges and handles Range for MP3/audio seeking."""

    protocol_version = "HTTP/1.1"

    def send_head(self):
        # Strip query string so paths like /audio/2.mp3?t=1 resolve correctly
        path_only = self.path.split("?", 1)[0]
        path = self.translate_path(path_only)
        if not os.path.isfile(path):
            return super().send_head()

        file_size = os.path.getsize(path)
        range_header = self.headers.get("Range")

        if range_header:
            # bytes=start-end (end optional) or bytes=-suffix (last N bytes)
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            suffix_m = re.match(r"bytes=-(\d+)$", range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else file_size - 1
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    start = 0
                    end = min(8191, file_size - 1)
                length = end - start + 1
            elif suffix_m and file_size > 0:
                # Suffix range: last N bytes (some players use this)
                length = min(int(suffix_m.group(1)), file_size)
                start = file_size - length
                end = file_size - 1
            else:
                range_header = None

            if range_header and (m or suffix_m):
                ctype = self.guess_type(path)
                with open(path, "rb") as f:
                    f.seek(start)
                    chunk = f.read(length)
                # Return BytesIO so exactly `length` bytes are sent (base class copies until EOF)
                body = io.BytesIO(chunk)

                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if path.replace("\\", "/").endswith(".json") and "timestamps" in path:
                    self.send_header("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                self.end_headers()
                return body

        f = open(path, "rb")
        self.send_response(200)
        ctype = self.guess_type(path)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        # Never cache timestamp JSON so clients always get latest word-level data
        if path.replace("\\", "/").endswith(".json") and "timestamps" in path:
            self.send_header("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate")
            self.send_header("Pragma", "no-cache")
        self.end_headers()
        return f


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    try:
        server = ThreadedHTTPServer(("", PORT), RangeRequestHandler)
    except OSError as e:
        if e.errno == 10048 or "WinError 10048" in str(e) or "address already in use" in str(e).lower():
            print(f"ERROR: Port {PORT} is already in use. Close the other app using it or use: py serve_fast.py 3001")
        else:
            print(f"ERROR: {e}")
        sys.exit(1)
    print(f"Serving at http://localhost:{PORT} (threaded + MP3 range support)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()