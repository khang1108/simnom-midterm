import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.aligner.book_aligner import BookAligner
from src.evaluator.exporter import AlignmentExporter


class DictionaryStub:
    def is_phonetic_match(self, char, syllable):
        return {'天': 'thiên', '地': 'địa'}.get(char) == syllable.lower()


class BookAlignerTests(unittest.TestCase):
    def setUp(self):
        self.aligner = BookAligner(DictionaryStub())

    def test_projection_preserves_unmatched_characters(self):
        for text in ['甲天地', '天甲地', '天地甲', '甲天地乙']:
            with self.subTest(text=text):
                pairs = self.aligner.align_and_project_page(text, ['Thiên.', 'Địa.'])
                self.assertEqual(''.join(ch for ch, _ in pairs), text)

    def test_projection_preserves_text_when_last_sentence_has_no_match(self):
        pairs = self.aligner.align_and_project_page('天甲', ['Thiên.', 'Địa.', 'Thiên.'])
        self.assertEqual(''.join(ch for ch, _ in pairs), '天甲')
        self.assertEqual([vi for _, vi in pairs], ['Thiên.', 'Địa.', 'Thiên.'])

    def align_fixture(self, ch_pages, vi_pages, pairs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for script, pages in [('ch', ch_pages), ('vi', vi_pages)]:
                (root / script).mkdir()
                (root / script / 'Label.txt').write_text(''.join(
                    f'{script}/{name}\t{json.dumps([{"transcription": text}], ensure_ascii=False)}\n'
                    for name, text in pages.items()
                ), encoding='utf-8')
            (root / 'Book_image_map.json').write_text(json.dumps({'pairs': pairs}), encoding='utf-8')
            captured = []
            with patch.object(AlignmentExporter, 'export_csv', side_effect=lambda rows, _: captured.extend(rows)), \
                 patch.object(AlignmentExporter, 'export_xlsx'):
                self.aligner.align_book(str(root), 'Book')
            return captured

    def test_cross_pair_sentence_is_stitched_and_next_sentence_keeps_source(self):
        rows = self.align_fixture(
            {'Book.004.jpg': '天', 'Book.003.jpg': '地天'},
            {'Book.001.jpg': 'Thiên', 'Book.002.jpg': 'địa. Thiên.'},
            [{'ch': ['Book.004.jpg'], 'vi': ['Book.001.jpg']},
             {'ch': ['Book.003.jpg'], 'vi': ['Book.002.jpg']}],
        )
        self.assertEqual([(r['ch_txt'], r['vi_txt']) for r in rows],
                         [('天地', 'Thiên địa.'), ('天', 'Thiên.')])
        self.assertEqual([r['sentence_id'] for r in rows], ['Book.004.1', 'Book.003.1'])

    def test_sentence_spans_three_pairs(self):
        rows = self.align_fixture(
            {'Book.006.jpg': '天', 'Book.005.jpg': '地', 'Book.004.jpg': '天'},
            {'Book.001.jpg': 'Thiên', 'Book.002.jpg': 'địa', 'Book.003.jpg': 'thiên.'},
            [{'ch': [f'Book.{6-i:03d}.jpg'], 'vi': [f'Book.{i+1:03d}.jpg']} for i in range(3)],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ch_txt'], '天地天')
        self.assertEqual(rows[0]['sentence_id'], 'Book.006.1')

    def test_short_boxes_survive(self):
        for text in ['天', '天地']:
            with self.subTest(text=text):
                rows = self.align_fixture({'Book.004.jpg': text}, {'Book.001.jpg': 'Thiên địa.'},
                                          [{'ch': ['Book.004.jpg'], 'vi': ['Book.001.jpg']}])
                self.assertEqual(''.join(row['ch_txt'] for row in rows), text)

    def test_many_to_many_mapping_preserves_reading_order_and_provenance(self):
        rows = self.align_fixture(
            {'Book.004.jpg': '天', 'Book.003.jpg': '地'},
            {'Book.001.jpg': 'Thiên.', 'Book.002.jpg': 'Địa.'},
            [{'ch': ['Book.004.jpg', 'Book.003.jpg'], 'vi': ['Book.001.jpg', 'Book.002.jpg']}],
        )
        self.assertEqual([(r['ch_txt'], r['vi_txt']) for r in rows], [('天', 'Thiên.'), ('地', 'Địa.')])
        self.assertEqual([r['sentence_id'] for r in rows], ['Book.004.1', 'Book.003.1'])
        self.assertTrue(all(not AlignmentExporter.validate_row(r) for r in rows))

    def test_sentence_spanning_images_uses_first_image(self):
        rows = self.align_fixture(
            {'Book.004.jpg': '天', 'Book.003.jpg': '地'},
            {'Book.001.jpg': 'Thiên địa.'},
            [{'ch': ['Book.004.jpg', 'Book.003.jpg'], 'vi': ['Book.001.jpg']}],
        )
        self.assertEqual(rows[0]['ch_txt'], '天地')
        self.assertEqual(rows[0]['img_id'], 'Book.004.jpg')


if __name__ == '__main__':
    unittest.main()
