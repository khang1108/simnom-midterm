import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
from src.aligner.dp_align import PhoneticDPAligner
from src.aligner.book_aligner import BookAligner
from src.evaluator.exporter import AlignmentExporter
from src.ocr.engine import OCREngine


class DictionaryStub:
    def is_phonetic_match(self, char, syllable):
        return char == '天' and syllable.lower() == 'thiên'


class RemainingFixTests(unittest.TestCase):
    def test_no_scored_data_is_not_a_pass(self):
        for rows in [[], [{'ch_txt': '天', 'text_diff': None}],
                     [{'ch_txt': '[MASK]', 'text_diff': []}],
                     [{'ch_txt': '天', 'text_diff': [{'type': 'warn', 'nom_pos': [[0, 1]]}]}]]:
            metrics = AlignmentExporter.evaluate_dataset(rows)
            self.assertIsNone(metrics['similarity_percent'])
            self.assertFalse(metrics['is_passing'])
            self.assertFalse(metrics['evaluation_applicable'])
        metrics = AlignmentExporter.evaluate_dataset([{'ch_txt': '天', 'text_diff': []}])
        self.assertTrue(metrics['is_passing'])
        self.assertEqual(metrics['similarity_percent'], 100)

    def test_mask_is_untouched_and_offsets_still_reference_original_text(self):
        result = PhoneticDPAligner(DictionaryStub()).align_sentence('[MASK]天地[MASK]', 'thiên sai')
        self.assertEqual(result['total_nom_chars'], 2)
        self.assertEqual(result['text_diff'][0]['nom_pos'], [[7, 8]])
        self.assertEqual(result['text_diff'][0]['nom_sub_text'], '地')
        row = {**result, 'img_id': 'B.001.jpg', 'sentence_id': 'B.001.1'}
        self.assertEqual(AlignmentExporter.validate_row(row), [])

    def test_projection_never_splits_mask(self):
        pairs = BookAligner(DictionaryStub()).align_and_project_page('[MASK]天[MASK]', ['Sai.', 'Thiên.'])
        self.assertEqual(''.join(ch for ch, _ in pairs), '[MASK]天[MASK]')
        self.assertEqual(sum(ch.count('[MASK]') for ch, _ in pairs), 2)

    def test_vision_text_is_bound_to_its_crop_even_when_header_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page.jpg'
            cv2.imwrite(str(path), np.full((60, 100, 3), 255, dtype=np.uint8))
            regions = [[[0, 0], [100, 0], [100, 10], [0, 10]],
                       [[5, 20], [95, 20], [95, 40], [5, 40]]]
            engine = OCREngine.__new__(OCREngine)
            engine.openai_key = 'test'
            engine.openai_base_url = 'https://example.invalid'
            engine.openai_model = 'test'
            def reply(url, json=None, **kw):
                response = Mock()
                crop = cv2.imdecode(np.frombuffer(__import__('base64').b64decode(
                    json['messages'][0]['content'][0]['image_url']['url'].split(',', 1)[1]), np.uint8), cv2.IMREAD_COLOR)
                response.json.return_value = {'choices': [{'message': {'content': 'Thiên địa' if crop.shape[0] > 20 else ''}}]}
                return response
            with patch.object(engine, '_detect_line_boxes_opencv', return_value=regions) as detect, \
                 patch('src.ocr.engine.requests.post', side_effect=reply) as post:
                boxes = engine._ocr_openai_vision(path, script='ch')
            detect.assert_called_once_with(path, script='ch')
            self.assertEqual(boxes, [{'transcription': 'Thiên địa', 'points': regions[1]}])
            self.assertEqual(post.call_count, 2)

    def test_vision_skips_zero_area_box_without_request(self):
        engine = OCREngine.__new__(OCREngine)
        with patch('src.ocr.engine.cv2.imread', return_value=np.zeros((10, 10, 3), dtype=np.uint8)), \
             patch.object(engine, '_detect_line_boxes_opencv', return_value=[[[0, 0]] * 4]), \
             patch('src.ocr.engine.requests.post') as post:
            self.assertEqual(engine._ocr_openai_vision(Path('page.jpg'), script='ch'), [])
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
