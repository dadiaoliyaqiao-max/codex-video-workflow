"""Synthetic cover approval tests; isolates file hashes, not video decoding or artwork quality."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest

from PIL import Image

import cover
import flow


class CoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent / '_verification' / ('cover_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        cls.root.mkdir(parents=True)

    def fixture(self, required=True):
        project = self.root / self.id().split('.')[-1]
        flow.init_project(argparse.Namespace(project=str(project), name='合成封面确认验证', synthetic=True))
        paths = flow.project_paths(project)
        source = project / '素材/SYNTHETIC_byte_fixture.mp4'
        source.write_bytes(b'BYTE-ONLY SYNTHETIC INPUT; NOT A DECODING TEST')
        brief = flow.read_json(paths['brief'])
        brief.update(objective='合成文件指纹验证，不是实际视频制作', target_duration_s=2, aspect_ratio='16:9', fps='30', required_content=[])
        if required is None:
            brief.pop('cover')
        else:
            brief['cover'].update(required=required, title='合成测试封面')
        flow.write_json(paths['brief'], brief)
        flow.write_json(paths['manifest'], {'sources': [{'id': 'M001', 'path': str(source), 'sha256': flow.sha256(source), 'duration': 3}], 'references': []})
        paths['strategy'].write_text('This synthetic test verifies cover approval fingerprints and file references only. '
            'A byte fixture stands in for the video so tests do not assert video decoding or visual quality. '
            'All confirmations are explicitly synthetic and have no authority over real projects.', encoding='utf-8')
        image = paths['edit'] / '02_storyboard/frame.png'
        Image.new('RGB', (160, 90), '#8899AA').save(image)
        flow.write_json(paths['board'], {'shots': [{'id': 'S1', 'source': 'M001', 'start': 0, 'end': 2,
            'frame': 1, 'frame_path': '02_storyboard/frame.png', 'key_content': '合成色块，不是真实拍摄素材', 'covers': []}]})
        paths['board_html'].write_text('<html><body>SYNTHETIC COVER HASH TEST</body></html>', encoding='utf-8')
        flow.write_json(paths['edl'], {'version': 1, 'sources': {'M001': str(source)},
            'ranges': [{'source': 'M001', 'start': 0, 'end': 2}], 'total_duration_s': 2})
        self.approve(paths, 'strategy')
        self.approve(paths, 'storyboard')
        preview = paths['edit'] / '03_preview/SYNTHETIC_preview_byte_fixture.bin'
        preview.write_bytes(b'BYTE-ONLY PREVIEW FIXTURE; NOT A REAL VIDEO')
        qa = preview.with_suffix('.qa.json')
        flow.write_json(qa, {'technical_passed': True, 'video_sha256': flow.sha256(preview),
            'scope': 'Stubbed technical QA solely for preview/cover fingerprint tests, not media validation.'})
        state = flow.state_for(paths)
        state['renders']['preview'] = {'file': str(preview), 'qa_file': str(qa),
            'storyboard_digest': flow.stage_digest(paths, 'storyboard'), 'synthetic': True}
        flow.write_json(paths['state'], state)
        return paths

    def approve(self, paths, stage):
        return flow.approve_stage(argparse.Namespace(project=str(paths['root']), stage=stage,
            message='SYNTHETIC COVER TEST ONLY; NOT A HUMAN APPROVAL', synthetic_test=True))

    def add_cover(self, paths, with_reference=False):
        picture = paths['edit'] / 'cover/cover_v001.png'
        Image.new('RGB', (120, 160), '#336699').save(picture)
        source_files = []
        if with_reference:
            reference = paths['root'] / '封面参考/SYNTHETIC_reference.png'
            Image.new('RGB', (120, 160), '#CCAA88').save(reference)
            source_files = ['../封面参考/SYNTHETIC_reference.png']
        flow.write_json(paths['edit'] / 'cover/cover_manifest.json', {'version': 1, 'title': '合成测试封面',
            'files': [{'file': 'cover/cover_v001.png', 'role': 'primary'}], 'source_files': source_files})
        return picture

    def test_new_projects_require_cover(self):
        paths = self.fixture()
        self.assertTrue(flow.read_json(paths['brief'])['cover']['required'])
        self.assertTrue((paths['root'] / '封面参考').is_dir())
        with self.assertRaisesRegex(ValueError, '要求封面'):
            self.approve(paths, 'preview')

    def test_legacy_no_cover_is_compatible(self):
        paths = self.fixture(required=None)
        self.approve(paths, 'preview')
        flow.require_approval(paths, 'preview')

    def test_valid_cover_changes_preview_not_storyboard(self):
        paths = self.fixture()
        board = flow.require_approval(paths, 'storyboard')
        picture = self.add_cover(paths)
        self.assertEqual(flow.require_approval(paths, 'storyboard'), board)
        self.approve(paths, 'preview')
        flow.require_approval(paths, 'preview')
        Image.new('RGB', (120, 160), '#CC3344').save(picture)
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'preview')
        # No video render is needed to approve a new cover with the unchanged preview.
        self.approve(paths, 'preview')
        flow.require_approval(paths, 'preview')

    def test_declared_reference_change_invalidates_strategy(self):
        paths = self.fixture()
        self.add_cover(paths, with_reference=True)
        brief = flow.read_json(paths['brief'])
        brief['cover']['reference_files'] = ['../封面参考/SYNTHETIC_reference.png']
        flow.write_json(paths['brief'], brief)
        self.approve(paths, 'strategy')
        self.approve(paths, 'storyboard')
        state = flow.state_for(paths)
        state['renders']['preview']['storyboard_digest'] = flow.stage_digest(paths, 'storyboard')
        flow.write_json(paths['state'], state)
        self.approve(paths, 'preview')
        reference = paths['root'] / '封面参考/SYNTHETIC_reference.png'
        Image.new('RGB', (120, 160), '#223344').save(reference)
        with self.assertRaisesRegex(flow.FlowError, '旧确认失效'):
            flow.require_approval(paths, 'strategy')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'preview')

    def test_manifest_source_change_invalidates_preview(self):
        paths = self.fixture()
        self.add_cover(paths, with_reference=True)
        self.approve(paths, 'preview')
        reference = paths['root'] / '封面参考/SYNTHETIC_reference.png'
        Image.new('RGB', (120, 160), '#553322').save(reference)
        with self.assertRaisesRegex(flow.FlowError, '旧确认失效'):
            flow.require_approval(paths, 'preview')

    def test_invalid_image_and_missing_reference_rejected(self):
        paths = self.fixture()
        picture = self.add_cover(paths)
        picture.write_bytes(b'not an image')
        with self.assertRaisesRegex(ValueError, '无法解码'):
            cover.validate_cover(paths, flow.read_json(paths['brief']))
        Image.new('RGB', (120, 160), '#334455').save(picture)
        brief = flow.read_json(paths['brief'])
        brief['cover']['reference_files'] = ['../封面参考/missing.png']
        with self.assertRaisesRegex(ValueError, '全部参考图'):
            cover.validate_cover(paths, brief)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoverTests))
    report = {'synthetic_only': True, 'tests_run': result.testsRun, 'passed': result.wasSuccessful(),
        'failures': len(result.failures), 'errors': len(result.errors),
        'scope': 'Cover image decoding and combined preview approval hashes; byte-only video fixture, not rendering validation.',
        'artifacts': str(CoverTests.root)}
    flow.write_json(CoverTests.root / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
