"""Check evidence preservation and boundaries, not drawing aesthetics."""
import json
import base64
from types import SimpleNamespace
from unittest.mock import patch
import pymupdf
from pathlib import Path
import sys
import tempfile
import unittest

from harness.model_led_drawing import digest, execute, prepare, record_review, verify, write, figure_contract, deliver


class ModelLedDrawingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'run'
        self.root.mkdir()
        (self.root / 'inputs').mkdir()
        (self.root / 'iterations').mkdir()
        self.input = self.root / 'inputs' / 'paper.pdf'
        self.input.write_bytes(b'input snapshot')
        write(self.root / 'inputs.json', {'hashes': {'paper.pdf': digest(self.input)}})

    def test_same_paper_rejected_before_creation(self):
        new = Path(self.temp.name) / 'same-paper'
        with self.assertRaisesRegex(ValueError, 'different paper'):
            prepare(new, 'missing.pdf', 'missing.pptx', '123', '123', 'missing.txt')
        self.assertFalse(new.exists())

    def test_input_drift_rejected(self):
        self.input.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            verify(self.root)

    def test_multiple_reference_identities_match_files(self):
        new = Path(self.temp.name) / 'bad-reference-count'
        with self.assertRaisesRegex(ValueError, 'corresponding paper identity'):
            prepare(new, 'missing.pdf', ['a.pptx', 'b.pptx'], 'target', ['other'], 'request')
        self.assertFalse(new.exists())

    def test_reference_from_target_rejected(self):
        new = Path(self.temp.name) / 'bad-reference-id'
        with self.assertRaisesRegex(ValueError, 'different paper'):
            prepare(new, 'missing.pdf', ['a.pptx', 'b.pptx'], 'target', ['other', 'target'], 'request')
        self.assertFalse(new.exists())

    def image_inputs(self):
        pdf = Path(self.temp.name) / 'source.pdf'
        doc = pymupdf.open()
        doc.new_page().insert_text((20, 30), 'Technical input fixture')
        doc.save(pdf)
        doc.close()
        image = Path(self.temp.name) / 'reference.png'
        image.write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
        return pdf, image

    def test_minimum_input_images_and_derived_evidence_integrity(self):
        pdf, image = self.image_inputs()
        new = Path(self.temp.name) / 'minimal'
        prepare(new, pdf, [image, image])
        manifest = verify(new)
        self.assertEqual(manifest['figure_contract']['aspect_ratio'], [16, 9])
        self.assertEqual(len(manifest['style_references']), 2)
        self.assertIsNone(manifest['style_references'][0]['pptx'])
        self.assertIsNone(manifest['target_paper_id'])
        self.assertTrue((new / 'inputs/request.txt').read_text())
        (new / 'inputs/paper-text.txt').write_text('mutated derived evidence')
        with self.assertRaisesRegex(ValueError, 'Input evidence changed'):
            verify(new)

    def test_two_figures_from_same_other_paper_allowed(self):
        pdf, image = self.image_inputs()
        new = Path(self.temp.name) / 'same-other-paper'
        prepare(new, pdf, [image, image], 'target', ['other', 'other'])
        self.assertEqual(verify(new)['reference_paper_id'], 'other')

    def test_style_learning_guidance_is_snapshotted_and_protected(self):
        pdf, image = self.image_inputs()
        new = Path(self.temp.name) / 'style-evidence'
        prepare(new, pdf, [image])
        guide = new / 'STYLE_LEARNING.zh-CN.md'
        self.assertEqual(guide.read_bytes(),
            (Path(__file__).resolve().parents[1] / 'guides' / guide.name).read_bytes())
        verify(new)
        guide.write_text('Changed model style instructions')
        with self.assertRaisesRegex(ValueError, 'Input evidence changed'):
            verify(new)

    def test_missing_asset_does_not_create_partial_run(self):
        new = Path(self.temp.name) / 'missing'
        with self.assertRaises(FileNotFoundError):
            prepare(new, 'missing.pdf', 'missing.png')
        self.assertFalse(new.exists())

    def test_native_pair_index_must_exist(self):
        new = Path(self.temp.name) / 'bad-pair'
        with self.assertRaisesRegex(ValueError, 'existing reference'):
            prepare(new, 'missing.pdf', ['missing.png'], reference_native={2: 'missing.pptx'})

    def test_production_rejects_reference_pptx_before_creation(self):
        new = Path(self.temp.name) / 'production-native'
        with self.assertRaisesRegex(ValueError, 'images only'):
            prepare(new, 'missing.pdf', ['reference.pptx'])
        self.assertFalse(new.exists())

    def test_production_rejects_native_companion_before_creation(self):
        new = Path(self.temp.name) / 'production-companion'
        with self.assertRaisesRegex(ValueError, 'images only'):
            prepare(new, 'missing.pdf', ['reference.png'], reference_native={1:'native.pptx'})
        self.assertFalse(new.exists())
        self.assertFalse(new.exists())

    def test_ratio_and_single_slide_are_checked_without_resizing(self):
        with patch('harness.model_led_drawing.Presentation', return_value=SimpleNamespace(
                slide_width=1600, slide_height=900, slides=[None])):
            self.assertEqual(figure_contract('unused', {})['slide_count'], 1)
        with patch('harness.model_led_drawing.Presentation', return_value=SimpleNamespace(
                slide_width=1600, slide_height=1060, slides=[None])):
            with self.assertRaisesRegex(ValueError, '16:9'):
                figure_contract('unused', {})
        with patch('harness.model_led_drawing.Presentation', return_value=SimpleNamespace(
                slide_width=1600, slide_height=900, slides=[None, None])):
            with self.assertRaisesRegex(ValueError, 'main-figure slide'):
                figure_contract('unused', {})

    def test_v2_wrong_ratio_failure_retained_before_render(self):
        data = json.loads((self.root / 'inputs.json').read_text())
        data['figure_contract'] = {'aspect_ratio': [16, 9], 'slide_count': 1}
        (self.root / 'inputs.json').write_text(json.dumps(data))
        script = Path(self.temp.name) / 'wrong-size.py'
        script.write_text('from pathlib import Path\nimport sys\nPath(sys.argv[1], "candidate.pptx").write_bytes(b"fixture")\n')
        decision = Path(self.temp.name) / 'wrong-size.md'
        decision.write_text('Technical fixture')
        with patch('harness.model_led_drawing.Presentation', return_value=SimpleNamespace(
                slide_width=1600, slide_height=1060, slides=[None])), patch('harness.model_led_drawing.render') as renderer:
            with self.assertRaisesRegex(ValueError, '16:9'):
                execute(self.root, script, [sys.executable, '{builder}', '{output}'], decision)
            renderer.assert_not_called()
        failure = json.loads((self.root / 'iterations/000/failure.json').read_text())
        self.assertFalse(failure['automatic_retry'])
        self.assertFalse((self.root / 'iterations/000/candidate.json').exists())

    def test_failed_model_launch_preserved_not_retried(self):
        script = Path(self.temp.name) / 'fail.py'
        script.write_text('raise SystemExit(7)\n')
        decision = Path(self.temp.name) / 'decision.md'
        decision.write_text('Model chose this diagnostic launch.')
        with self.assertRaisesRegex(RuntimeError, 'builder failed'):
            execute(self.root, script, [sys.executable, '{builder}'], decision)
        folder = self.root / 'iterations' / '000'
        self.assertEqual(json.loads((folder / 'execution.json').read_text())['exit_code'], 7)
        self.assertEqual((folder / 'fail.py').read_text(), script.read_text())
        self.assertEqual(len(list((self.root / 'iterations').iterdir())), 1)
        self.assertFalse(json.loads((folder / 'failure.json').read_text())['automatic_retry'])
        self.assertFalse((folder / 'candidate.json').exists())

    def candidate(self):
        folder = self.root / 'iterations' / '000'
        folder.mkdir()
        (folder / 'render').mkdir()
        (folder / 'candidate.pptx').write_bytes(b'native candidate')
        (folder / 'render' / 'slide-01.png').write_bytes(b'actual render')
        write(folder / 'candidate.json', {
            'pptx_sha256': digest(folder / 'candidate.pptx'),
            'render_hashes': {'slide-01.png': digest(folder / 'render' / 'slide-01.png')}})
        review = Path(self.temp.name) / 'review.md'
        review.write_text('Free-form model observations and next drawing decisions.')
        return folder, review

    def test_render_drift_blocks_review(self):
        folder, review = self.candidate()
        (folder / 'render' / 'slide-01.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            record_review(self.root, '000', review)

    def test_review_keeps_human_acceptance_pending(self):
        folder, review = self.candidate()
        record_review(self.root, '000', review)
        record = json.loads((folder / 'review-record.json').read_text())
        self.assertEqual(record['human_acceptance'], 'pending')
        self.assertEqual((folder / 'model-review.md').read_text(), review.read_text())
        with self.assertRaises(FileExistsError):
            record_review(self.root, '000', review)

    def test_review_path_stays_in_iterations(self):
        _, review = self.candidate()
        with self.assertRaisesRegex(ValueError, 'local index'):
            record_review(self.root, '../inputs', review)
    def test_empty_review_rejected(self):
        _, review = self.candidate()
        review.write_text('  ')
        with self.assertRaisesRegex(ValueError, 'cannot be empty'):
            record_review(self.root, '000', review)

    def test_model_notes_reject_empty_or_unsafe_before_launch(self):
        note = Path(self.temp.name) / 'notes.md'
        note.write_text(' ')
        with self.assertRaisesRegex(ValueError, 'cannot be empty'):
            execute(self.root, 'unused', [], 'unused', {'understanding': note})
        note.write_text('Free-form mechanism reasoning')
        with self.assertRaisesRegex(ValueError, 'plain label'):
            execute(self.root, 'unused', [], 'unused', {'../escape': note})
        self.assertFalse(list((self.root / 'iterations').iterdir()))

    def test_model_notes_preserved_on_failed_attempt(self):
        script = Path(self.temp.name) / 'fail-with-notes.py'
        script.write_text('raise SystemExit(7)\n')
        note = Path(self.temp.name) / 'understanding.md'
        note.write_text('Model-authored science and source uncertainties')
        with self.assertRaisesRegex(RuntimeError, 'builder failed'):
            execute(self.root, script, [sys.executable, '{builder}'], note,
                    {'understanding': note})
        folder = self.root / 'iterations/000'
        self.assertEqual((folder / 'model-understanding.md').read_text(), note.read_text())
        self.assertEqual(json.loads((folder / 'launch.json').read_text())[
            'model_evidence_hashes']['model-understanding.md'], digest(note))

    def test_model_notes_drift_blocks_review_and_delivery(self):
        folder, review = self.candidate()
        note = folder / 'model-understanding.md'
        note.write_text('Initial model science understanding')
        write(folder / 'launch.json', {'model_evidence_hashes': {note.name: digest(note)}})
        note.write_text('Changed after candidate creation')
        with self.assertRaisesRegex(ValueError, 'Model evidence changed'):
            record_review(self.root, '000', review)
        with self.assertRaisesRegex(ValueError, 'Model evidence changed'):
            deliver(self.root, '000', Path(self.temp.name) / 'delivery', review)

    def test_delivery_requires_review_and_consistent_evidence(self):
        folder, review = self.candidate()
        out = Path(self.temp.name) / 'delivery'
        with self.assertRaises(FileNotFoundError):
            deliver(self.root, '000', out, review)
        self.assertFalse(out.exists())
        record_review(self.root, '000', review)
        (folder / 'render/slide-01.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Rendered evidence changed'):
            deliver(self.root, '000', out, review)
        self.assertFalse(out.exists())

    def test_delivery_rejects_review_mutation(self):
        folder, review = self.candidate()
        record_review(self.root, '000', review)
        (folder / 'model-review.md').write_text('changed review')
        with self.assertRaisesRegex(ValueError, 'review changed'):
            deliver(self.root, '000', Path(self.temp.name) / 'delivery', review)



if __name__ == '__main__':
    unittest.main()
