import unittest
from scripts.export_parallel_demo import locate_regions, body_boxes, DEFAULT_CH_ROI


class DemoRegionTests(unittest.TestCase):
    def test_default_roi_keeps_rightmost_column_of_page_586(self):
        box = {'transcription': '芇油奴固功庫辱体芇默𢚸',
               'points': [[3161, 865], [3288, 865], [3288, 5190], [3161, 5190]]}
        kept, excluded = body_boxes([box], (4445, 6306), DEFAULT_CH_ROI)
        self.assertEqual(kept, [box])
        self.assertEqual(excluded, [])

    def test_vertical_sentence_can_continue_into_next_column(self):
        boxes = [
            {'transcription': '天地', 'points': [[20, 0], [30, 0], [30, 20], [20, 20]]},
            {'transcription': '人', 'points': [[0, 0], [10, 0], [10, 10], [0, 10]]},
        ]
        regions = locate_regions(boxes, ['天', '地人'], True)
        self.assertEqual(len(regions[1]), 2)
        self.assertEqual(regions[0][0]['points'], [[20, 0], [30, 0], [30, 10], [20, 10]])

    def test_horizontal_regions_follow_exact_text_offsets(self):
        boxes = [{'transcription': 'Ta hay.', 'points': [[0, 0], [70, 0], [70, 10], [0, 10]]}]
        regions = locate_regions(boxes, ['Ta', 'hay.'], False)
        self.assertEqual(regions[1][0]['points'][0], [30, 0])

    def test_refuse_mismatched_or_unconsumed_text(self):
        boxes = [{'transcription': '天地', 'points': [[0, 0], [10, 0], [10, 20], [0, 20]]}]
        for sentences in [['地天'], ['天']]:
            with self.assertRaises(ValueError):
                locate_regions(boxes, sentences, True)
