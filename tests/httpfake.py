"""A small threaded HTTP server for tests: serves configurable bytes and headers.

    with FakeHttp(body=b'abc', etag='"v1"') as http:
        requests.head(http.url)
        http.body = b'other'      # mutable between requests
        http.head_count, http.get_count

HEAD and GET answer from the same config unless the get_* overrides are set,
which lets a test make GET differ from HEAD.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeHttp:
    def __init__(self, body=b'', etag=None, last_modified=None, length=None):
        self.body = body
        self.etag = etag
        self.last_modified = last_modified
        self.length = length  # Content-Length header override; default len(body)
        # GET-only overrides (None -> same as HEAD).
        self.get_body = None
        self.get_etag = None
        self.get_last_modified = None
        self.get_length = None
        # Send this many body bytes on GET, then drop the connection.
        self.drop_after = None
        self.head_count = 0
        self.get_count = 0
        self._server = None
        self._thread = None

    @property
    def url(self):
        return 'http://127.0.0.1:%d/app.apk' % self._server.server_address[1]

    def __enter__(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def _respond(self, is_get):
                if is_get:
                    fake.get_count += 1
                else:
                    fake.head_count += 1
                pick = lambda over, base: base if (not is_get or over is None) else over
                body = pick(fake.get_body, fake.body)
                etag = pick(fake.get_etag, fake.etag)
                last_modified = pick(fake.get_last_modified, fake.last_modified)
                length = pick(fake.get_length, fake.length)
                self.send_response(200)
                if etag is not None:
                    self.send_header('ETag', etag)
                if last_modified is not None:
                    self.send_header('Last-Modified', last_modified)
                self.send_header('Content-Length', str(len(body) if length is None else length))
                self.send_header('Connection', 'close')
                self.end_headers()
                if is_get:
                    if fake.drop_after is not None:
                        body = body[:fake.drop_after]
                    self.wfile.write(body)
                    self.wfile.flush()
                self.close_connection = True

            def do_HEAD(self):
                self._respond(False)

            def do_GET(self):
                self._respond(True)

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
