import ssl
import sys
import unittest

import anyio
import anyio.to_process
import idna
from anyio.streams.tls import TLSStream


def noisy_process():
    print("x" * (2 * 1024 * 1024), file=sys.stderr, flush=True)
    return "finished"


class StopBeforeHandshake(Exception):
    pass


class CaptureContext(ssl.SSLContext):
    def wrap_bio(self, incoming, outgoing, server_side=False, server_hostname=None, session=None):
        self.captured_hostname = server_hostname
        raise StopBeforeHandshake


class SecurityDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_uses_idna_2008_for_international_hostnames(self):
        for hostname, expected in (("faß.de", b"xn--fa-hia.de"), ("example.com", b"example.com")):
            with self.subTest(hostname=hostname):
                context = CaptureContext(ssl.PROTOCOL_TLS_CLIENT)
                with self.assertRaises(StopBeforeHandshake):
                    await TLSStream.wrap(object(), hostname=hostname, ssl_context=context)
                self.assertEqual(context.captured_hostname, expected)

    async def test_process_stderr_does_not_deadlock_the_worker(self):
        with anyio.fail_after(5):
            result = await anyio.to_process.run_sync(noisy_process, cancellable=True)
        self.assertEqual(result, "finished")

    def test_idna_rejects_oversized_contextual_labels(self):
        for hostname in ("\u0660" * 10000, "\u30fb" * 10000 + "\u6f22"):
            with self.subTest(character=hostname[0]):
                with self.assertRaises(idna.IDNAError):
                    idna.encode(hostname)
        self.assertEqual(idna.encode("example.com"), b"example.com")


if __name__ == "__main__":
    unittest.main()
