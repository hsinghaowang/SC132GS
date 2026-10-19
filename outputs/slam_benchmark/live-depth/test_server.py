"""Tests for stale-data rejection, invalid depth, and geometry failures."""
import io
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request

import numpy as np

from server import DepthFrame, ErrorCode, Pipeline, StereoDepth, ThreadingHTTPServer, handler_for


class DepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.processor = StereoDepth(Path(__file__).resolve().parent.parent /
            'calibration-ready-20261014/geometry-analysis/stereo-candidate.npz')

    def test_textureless_image_does_not_invent_depth(self):
        frame = self.processor.compute(np.zeros((1280, 2176), np.uint8), 1, time.monotonic(), 0.)
        depth = np.load(io.BytesIO(frame.depth_npy), allow_pickle=False)
        self.assertEqual(depth.shape, (640, 544))
        self.assertEqual(depth.dtype, np.float32)
        self.assertTrue(np.isnan(depth).all())
        self.assertEqual(frame.valid_fraction, 0.)

    def test_changed_stream_geometry_rejected(self):
        with self.assertRaises(ValueError):
            self.processor.compute(np.zeros((640, 1088), np.uint8), 1, time.monotonic(), None)

    def test_stale_http_data_and_failure_invalidation(self):
        pipeline = Pipeline(self.processor, 'unused')
        now = time.monotonic()
        pipeline.output = DepthFrame(1, now-3, now, b'jpeg', b'npy', b'png', .5, 50., 1.)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(pipeline))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            self.assertEqual(pipeline.status()['state'], 'unavailable')
            for path in ('/snapshot.jpg', '/depth.npy', '/mask.png', '/stream.mjpg'):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base+path, timeout=2)
                self.assertEqual(caught.exception.code, 503)
            pipeline.output = DepthFrame(2, time.monotonic(), time.monotonic(), b'jpeg', b'npy', b'png', .5, 50., 2.)
            with urllib.request.urlopen(base+'/snapshot.jpg', timeout=2) as response:
                self.assertEqual(response.read(), b'jpeg')
            pipeline.set_error(ErrorCode.CONNECT_OR_DECODE, 'test disconnect')
            self.assertIsNone(pipeline.fresh())
            self.assertEqual(pipeline.status()['state'], 'unavailable')
        finally:
            pipeline.stop.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
