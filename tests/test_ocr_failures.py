import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.ocr.engine import OCREngine
from src.ocr.runner import process_folder


class OCRFailureTests(unittest.TestCase):
    def test_failure_is_not_cached_and_next_call_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'page.jpg'
            image.write_bytes(b'image')
            engine = OCREngine.__new__(OCREngine)
            engine.cache_db = root / 'cache.db'
            engine._init_cache()
            engine.kim_token = 'test'
            engine.openai_key = None
            boxes = [{'transcription': '天', 'points': [[0, 0], [1, 0], [1, 1], [0, 1]]}]
            with patch.object(engine, '_ocr_kim_hannom', side_effect=[RuntimeError('API failed'), boxes]) as backend:
                with self.assertRaises(RuntimeError):
                    engine.recognize(image)
                self.assertIsNone(engine._get_cached_result(engine._get_file_hash(image), 'ch'))
                self.assertEqual(engine.recognize(image), boxes)
                self.assertEqual(engine.recognize(image), boxes)
                self.assertEqual(backend.call_count, 2)

    def test_legacy_empty_cache_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'page.jpg'
            image.write_bytes(b'image')
            engine = OCREngine.__new__(OCREngine)
            engine.cache_db = root / 'cache.db'
            engine._init_cache()
            engine.kim_token = 'test'
            engine.openai_key = None
            engine._save_cached_result(engine._get_file_hash(image), image.name, 'ch', 'unknown', [])
            with patch.object(engine, '_ocr_kim_hannom', return_value=[]) as backend:
                with self.assertRaises(RuntimeError):
                    engine.recognize(image)
                backend.assert_called_once()

    def test_runner_preserves_existing_labels_on_empty_or_failed_ocr(self):
        for result in [[], RuntimeError('API failed')]:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'page.jpg').write_bytes(b'image')
                for name in ['Label.txt', 'fileState.txt', 'Label_char.txt', 'fileState_char.txt']:
                    (root / name).write_text('existing annotations', encoding='utf-8')
                engine = Mock()
                if isinstance(result, Exception):
                    engine.recognize.side_effect = result
                else:
                    engine.recognize.return_value = result
                with self.assertRaises(RuntimeError):
                    process_folder(root, 'ch', engine)
                for name in ['Label.txt', 'fileState.txt', 'Label_char.txt', 'fileState_char.txt']:
                    self.assertEqual((root / name).read_text(), 'existing annotations')


if __name__ == '__main__':
    unittest.main()
