import hashlib
import importlib.util
from pathlib import Path
import unittest
import io
import ssl
from contextlib import redirect_stderr
from urllib.error import HTTPError
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("observe_pdfs", Path(__file__).parents[1] / "scripts/observe-content-pdfs.py")
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
URL = "https://nthszgnbqgjfqnzgytym.supabase.co/storage/v1/object/public/pdfs/example.pdf"
PUBLIC_DNS = [(2, 1, 6, "", ("104.18.20.20", 443))]


class Response:
    def __init__(self, raw, url=URL): self.raw, self.url = raw, url
    def geturl(self): return self.url
    def read(self, size):
        result, self.raw = self.raw[:size], self.raw[size:]
        return result
    def __enter__(self): return self
    def __exit__(self, *args): pass


class Opener:
    def __init__(self, raw, url=URL): self.raw, self.url, self.request = raw, url, None
    def open(self, request, timeout):
        self.request = request
        return Response(self.raw, self.url)


class ObserveTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch.object(observer.socket, "getaddrinfo", return_value=PUBLIC_DNS)
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def test_hash_without_credentials(self):
        raw = b"%PDF-1.7\nminimal test bytes"
        opener = Opener(raw)
        self.assertEqual(observer.observe(URL, opener), hashlib.sha256(raw).hexdigest())
        self.assertNotIn("Authorization", dict(opener.request.header_items()))
        self.assertNotIn("Cookie", dict(opener.request.header_items()))

    def test_changed_bytes_same_url(self):
        self.assertNotEqual(observer.observe(URL, Opener(b"%PDF-1.7 old")),
                            observer.observe(URL, Opener(b"%PDF-1.7 new")))

    def test_percent_encoded_extension(self):
        url = URL.replace(".pdf", "%2Epdf")
        self.assertEqual(observer.observe(url, Opener(b"%PDF-1.7 encoded", url)),
                         hashlib.sha256(b"%PDF-1.7 encoded").hexdigest())

    def test_discovery_uses_detector_external_pdf_scope(self):
        encoded = URL.replace(".pdf", "%2Epdf")
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "ko").mkdir()
            (repository / "ko/report.html").write_text(
                '<html><a href="' + encoded + '">Report</a>'
                '<a href="https://127.0.0.1/x.pdf">Private</a>'
                '<a href="https://private.internal/x.pdf">Internal</a>'
                '<a href="https://u:p@assets.example.com/x.pdf">Credential</a>'
                '<a href="https://other.example.com/x.pdf">Unapproved origin</a></html>',
                encoding="utf-8")
            self.assertEqual(observer.urls(repository),
                             sorted([encoded, "https://other.example.com/x.pdf"]))

    def test_origin_allowlist(self):
        for url in ("https://evil.example/x.pdf", "http://metanomia.org/x.pdf",
                    "https://u:p@metanomia.org/x.pdf", "https://metanomia.org:444/x.pdf",
                    "https://metanomia.org/x.txt", "file:///x.pdf"):
            with self.subTest(url=url), self.assertRaises(ValueError): observer.validate_url(url)

    def test_private_dns_rejected(self):
        with patch.object(observer.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError): observer.validate_url(URL)

    def test_cloud_eai_again_uses_unchanged_https_transport(self):
        raw = b"%PDF-1.7 cloud standard transport"
        log = io.StringIO()
        error = observer.socket.gaierror(observer.socket.EAI_AGAIN, "temporary name resolution failure")
        with patch.object(observer.socket, "getaddrinfo", side_effect=error), redirect_stderr(log):
            self.assertEqual(observer.observe(URL, Opener(raw)), hashlib.sha256(raw).hexdigest())
        self.assertIn("dns_preflight_unavailable", log.getvalue())
        self.assertIn("IP preflight was not verified", log.getvalue())

    def test_private_mixed_and_empty_dns_block_before_transport(self):
        for addresses in ([], [(2, 1, 6, "", ("10.0.0.1", 443))],
                          [(2, 1, 6, "", ("169.254.169.254", 443))],
                          PUBLIC_DNS + [(2, 1, 6, "", ("127.0.0.1", 443))]):
            opener = Mock()
            with self.subTest(addresses=addresses), patch.object(observer.socket, "getaddrinfo", return_value=addresses):
                with self.assertRaises(ValueError): observer.observe(URL, opener)
            opener.open.assert_not_called()

    def test_other_dns_errors_do_not_fall_back(self):
        errors = [observer.socket.gaierror(observer.socket.EAI_NONAME, "not found"),
                  PermissionError("denied"), TimeoutError("timeout"), OSError("other")]
        for error in errors:
            opener = Mock()
            with self.subTest(error=error), patch.object(observer.socket, "getaddrinfo", side_effect=error):
                with self.assertRaises(type(error)): observer.observe(URL, opener)
            opener.open.assert_not_called()

    def test_https_failures_remain_errors_when_dns_preflight_unavailable(self):
        for error in (ssl.SSLError("certificate failure"), HTTPError(URL, 403, "denied", {}, None), TimeoutError("timeout")):
            opener = Mock()
            opener.open.side_effect = error
            dns_error = observer.socket.gaierror(observer.socket.EAI_AGAIN, "temporary")
            with self.subTest(error=error), patch.object(observer.socket, "getaddrinfo", side_effect=dns_error), redirect_stderr(io.StringIO()):
                with self.assertRaises(type(error)): observer.observe(URL, opener)
            opener.open.assert_called_once()

    def test_url_guards_remain_before_cloud_transport(self):
        for url in ("https://evil.example/x.pdf", "http://metanomia.org/x.pdf", "https://u:p@metanomia.org/x.pdf"):
            opener = Mock()
            error = observer.socket.gaierror(observer.socket.EAI_AGAIN, "temporary")
            with self.subTest(url=url), patch.object(observer.socket, "getaddrinfo", side_effect=error):
                with self.assertRaises(ValueError): observer.observe(url, opener)
            opener.open.assert_not_called()

    def test_final_redirect_guard_during_cloud_transport(self):
        error = observer.socket.gaierror(observer.socket.EAI_AGAIN, "temporary")
        with patch.object(observer.socket, "getaddrinfo", side_effect=error), redirect_stderr(io.StringIO()):
            with self.assertRaises(ValueError): observer.observe(URL, Opener(b"%PDF-1.7", "https://evil.example/a.pdf"))

    def test_pdf_and_size_checks_during_cloud_transport(self):
        for raw in (b"not pdf", b"%PDF-1.7 too long"):
            error = observer.socket.gaierror(observer.socket.EAI_AGAIN, "temporary")
            with self.subTest(raw=raw), patch.object(observer.socket, "getaddrinfo", side_effect=error), patch.object(observer, "MAX_BYTES", 8), redirect_stderr(io.StringIO()):
                with self.assertRaises(ValueError): observer.observe(URL, Opener(raw))

    def test_redirect_final_origin_rejected(self):
        with self.assertRaises(ValueError): observer.observe(URL, Opener(b"%PDF-1.7", "https://evil.example/a.pdf"))

    def test_html_is_not_pdf(self):
        with self.assertRaises(ValueError): observer.observe(URL, Opener(b"<html>login required</html>"))

    def test_size_bound(self):
        with patch.object(observer, "MAX_BYTES", 8):
            with self.assertRaises(ValueError): observer.observe(URL, Opener(b"%PDF-1.7 too long"))


if __name__ == "__main__": unittest.main()
