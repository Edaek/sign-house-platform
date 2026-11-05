"""Follow-up text that repeats a just-forwarded media caption must not become a second inbound."""
import time
import unittest
from types import SimpleNamespace

from gateway.burst_coalesce import MediaBurstCoalescer


class GatewayCaptionDedupTests(unittest.TestCase):
    def test_swallow_same_caption_after_private_media(self):
        forwarded = []
        coal = MediaBurstCoalescer(lambda *a, **k: forwarded.append((a, k)))
        msg = SimpleNamespace(
            from_jid='120363@g.us',
            author='1437@lid',
            text='1005',
            caption='1005',
        )
        coal.remember_forwarded_media(msg, '1005')
        follow = SimpleNamespace(
            from_jid='120363@g.us',
            author='1437@lid',
            text='1005',
            caption='',
        )
        self.assertTrue(coal.attach_classify_text(follow))
        self.assertEqual(forwarded, [])

    def test_attach_to_open_burst_still_works(self):
        coal = MediaBurstCoalescer(lambda *a, **k: None)
        media = SimpleNamespace(
            from_jid='120363@g.us',
            author='1437@lid',
            text='',
            caption='',
            id='m1',
        )
        coal.submit(media, ['/tmp/a.jpg'], True)
        follow = SimpleNamespace(
            from_jid='120363@g.us',
            author='1437@lid',
            text='1007',
            caption='',
        )
        self.assertTrue(coal.attach_classify_text(follow))
        key = coal._key(media)
        buf = coal._bufs.get(key) or {}
        self.assertEqual(buf.get('classify_text'), '1007')
        timer = buf.get('timer')
        if timer:
            timer.cancel()


if __name__ == '__main__':
    unittest.main()
