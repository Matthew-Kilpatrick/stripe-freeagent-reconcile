import http.server
import socketserver
import threading
import time
from urllib.parse import urlparse, parse_qs

callback_data = {}

class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get('code')[0]
        callback_data['code'] = code
        # Handle the request, process the callback, etc.
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"OAuth callback received! You can now close this window.")

        # Shutdown the server after receiving the request
        threading.Thread(target=self.server.shutdown).start()


def _run_server(port):
    handler = OAuthCallbackHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving at port {port}")
        httpd.serve_forever()


def start_server(port):
    # Run the server in a separate thread
    server_thread = threading.Thread(target=_run_server, args=[port], daemon=True)
    server_thread.start()

    # Simulate waiting for a callback (timeout after some time if needed)
    try:
        while server_thread.is_alive():
            time.sleep(1)
        return callback_data
    except KeyboardInterrupt:
        print("Server manually interrupted.")
        exit()