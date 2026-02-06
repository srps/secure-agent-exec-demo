import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class ExfilHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/exfiltrate":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode("utf-8"))
            print("[exfiltrate] received JSON:")
            print(json.dumps(data, indent=2, sort_keys=True))
        except Exception:
            print("[exfiltrate] received raw bytes:")
            print(body)

        self.send_response(204)
        self.end_headers()

    def log_message(self, format, *args):
        return


def main():
    server = HTTPServer(("127.0.0.1", 8000), ExfilHandler)
    print("Listening on http://127.0.0.1:8000/exfiltrate")
    server.serve_forever()


if __name__ == "__main__":
    main()
