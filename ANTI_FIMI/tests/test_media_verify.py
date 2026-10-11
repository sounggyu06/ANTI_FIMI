"""SDK-independent unit tests with a small Reader fake."""
import io
import unittest
from unittest.mock import patch
from email.message import Message
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media_verify as mv

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00'*64
JPEG = b'\xff\xd8\xff' + b'\x00'*64
WEBP = b'RIFF\x3c\x00\x00\x00WEBP' + b'\x00'*64


class FakeSDK:
    def __init__(self, report=None, error=None):
        self.report = report or {}
        self.error = error
        self.arguments = None
        outer = self

        class Reader:
            def __init__(self, mime, stream):
                outer.arguments = (mime, stream.read())
                if outer.error:
                    raise outer.error
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def json(self):
                import json
                return json.dumps(outer.report)
        self.Reader = Reader


def report(state=None, source=None, errors=None):
    entry = {'claim_generator': 'Example Studio', 'signature_info': {'issuer': 'Example CA'},
             'assertions': [{'label': 'c2pa.actions.v2', 'data': {'actions': [
                 {'action': 'c2pa.created', 'digitalSourceType': source} if source else {'action': 'c2pa.created'}
             ]}}]}
    obj = {'active_manifest': 'urn:active', 'manifests': {'urn:active': entry}}
    if state:
        obj['validation_state'] = state
    if errors:
        obj['validation_status'] = errors
    return obj


class MediaVerifierTest(unittest.TestCase):
    def test_supported_image_sniff(self):
        self.assertEqual(mv.identify_image(PNG), 'image/png')
        self.assertEqual(mv.identify_image(JPEG), 'image/jpeg')
        self.assertEqual(mv.identify_image(WEBP), 'image/webp')
        self.assertIsNone(mv.identify_image(b'GIF89a'))

    def test_trusted_and_ai_record(self):
        sdk = FakeSDK(report('Trusted', 'http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia'))
        status, output = mv.verify_bytes(PNG, 'image/png', sdk=sdk)
        self.assertEqual(status, 200)
        self.assertEqual(output['status'], 'trusted')
        self.assertEqual(output['ai_record'], 'recorded')
        self.assertEqual(sdk.arguments, ('image/png', PNG))

    def test_valid_not_trusted(self):
        status, output = mv.verify_bytes(JPEG, 'image/jpeg', sdk=FakeSDK(report('Valid')))
        self.assertEqual((status, output['status'], output['ai_record']), (200, 'valid_untrusted', 'not_recorded'))

    def test_unknown_state_not_trusted(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK(report()))
        self.assertEqual(output['status'], 'valid_untrusted')

    def test_invalid_report(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK(report('Invalid')))
        self.assertEqual(output['status'], 'invalid')

    def test_failure_code(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK(report('Valid', errors=[{'code': 'claim.signature.mismatch'}])))
        self.assertEqual(output['status'], 'invalid')

    def test_missing_manifest(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK({'manifests': {}}))
        self.assertEqual(output['status'], 'missing')
        self.assertEqual(output['ai_record'], 'unknown')

    def test_sdk_not_found_error(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK(error=RuntimeError('ManifestNotFound')))
        self.assertEqual(output['status'], 'missing')

    def test_sdk_corrupted(self):
        _, output = mv.verify_bytes(PNG, 'image/png', sdk=FakeSDK(error=ValueError('Cannot decode CBOR')))
        self.assertEqual(output['status'], 'unavailable')

    def test_mismatched_mime(self):
        status, output = mv.verify_bytes(PNG, 'image/jpeg', sdk=FakeSDK(report('Trusted')))
        self.assertEqual((status, output['status']), (415, 'rejected'))

    def test_oversize(self):
        status, _ = mv.verify_bytes(PNG + b'0'*mv.MAX_IMAGE_BYTES, 'image/png', sdk=FakeSDK())
        self.assertEqual(status, 413)

    def test_empty(self):
        status, _ = mv.verify_bytes(b'', 'image/png', sdk=FakeSDK())
        self.assertEqual(status, 413)

    def test_bad_file(self):
        status, _ = mv.verify_bytes(b'<svg></svg>', 'image/png', sdk=FakeSDK())
        self.assertEqual(status, 415)

    def test_request_upload(self):
        headers = Message()
        headers['Content-Type'] = 'image/png'
        headers['Content-Length'] = str(len(PNG))
        with patch.object(mv, 'verify_bytes', return_value=(200, {'status': 'trusted'})) as fn:
            status, response = mv.handle_upload(headers, io.BytesIO(PNG))
        self.assertEqual(response['status'], 'trusted')
        fn.assert_called_once_with(PNG, 'image/png')

    def test_upload_incomplete(self):
        headers = {'Content-Type': 'image/png', 'Content-Length': '99'}
        status, response = mv.handle_upload(headers, io.BytesIO(PNG))
        self.assertEqual((status, response['status']), (400, 'rejected'))

    def test_upload_invalid_length(self):
        headers = {'Content-Type': 'image/png', 'Content-Length': 'nan'}
        self.assertEqual(mv.handle_upload(headers, io.BytesIO(PNG))[0], 411)

    def test_upload_oversize_without_read(self):
        class GuardStream:
            def read(self, count):
                raise AssertionError('Do not read huge upload')
        headers = {'Content-Type': 'image/png', 'Content-Length': str(mv.MAX_IMAGE_BYTES + 1)}
        self.assertEqual(mv.handle_upload(headers, GuardStream())[0], 413)

    def test_upload_wrong_media(self):
        headers = {'Content-Type': 'image/svg+xml', 'Content-Length': '15'}
        self.assertEqual(mv.handle_upload(headers, io.BytesIO(b'foo'))[0], 415)

    def test_upload_chunked(self):
        headers = {'Transfer-Encoding': 'chunked'}
        self.assertEqual(mv.handle_upload(headers, io.BytesIO(b'foo'))[0], 400)

    def test_no_ai_fabrication(self):
        obj = report('Trusted', 'http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture')
        self.assertEqual(mv.interpret_report(obj, 'a'*64, 12, 'image/jpeg')['ai_record'], 'not_recorded')


if __name__ == '__main__':
    unittest.main()
