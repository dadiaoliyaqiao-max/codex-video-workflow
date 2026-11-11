"""Synthetic technical verification only. No real user confirmation or media is used."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('video_flow', HERE / 'flow.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = HERE / '_verification' / ('controller_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        cls.root.mkdir(parents=True)
        cls.source = cls.root / 'SYNTHETIC_source.mp4'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=3',
            '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=3',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', cls.source))
        cls.frame = cls.root / 'SYNTHETIC_frame.png'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error', '-ss', '1', '-i', cls.source,
            '-frames:v', '1', '-update', '1', cls.frame))
        cls.silent = cls.root / 'SYNTHETIC_no_audio.mp4'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error', '-i', cls.source,
            '-c:v', 'copy', '-an', cls.silent))

    def fixture(self):
        name = self.id().split('.')[-1]
        p = self.root / name
        flow.init_project(argparse.Namespace(project=str(p), name=name, synthetic=True))
        paths = flow.project_paths(p)
        source = p / '素材/source.mp4'
        shutil.copyfile(self.source, source)
        brief = flow.read_json(paths['brief'])
        brief.update(objective='合成技术验收，不是真实剪辑任务', target_duration_s=2,
                     aspect_ratio='16:9', required_content=['合成测试标识'], cover={'required': False})
        flow.write_json(paths['brief'], brief)
        flow.write_json(paths['manifest'], {'sources': [{'id': 'M001', 'path': str(source),
            'sha256': flow.sha256(source), 'duration': 3, 'width': 640, 'height': 360, 'has_audio': True}], 'references': []})
        paths['strategy'].write_text(('This synthetic verification uses a two-second color-bar clip with a sine tone. '
            'Keep the single segment intact, retain the technical pattern, and label every verification artifact as synthetic. '
            'No real user content or approval is represented by this fixture.\n'), encoding='utf-8')
        frame = p / 'edit/02_storyboard/frame.png'
        shutil.copyfile(self.frame, frame)
        flow.write_json(paths['board'], {'shots': [{'id': 'S01', 'source': 'M001', 'start': 0,
            'end': 2, 'frame': 1, 'frame_path': '02_storyboard/frame.png',
            'key_content': '合成测试图案', 'covers': ['合成测试标识']}]})
        paths['board_html'].write_text('<html><body>SYNTHETIC TEST<img src="frame.png"></body></html>', encoding='utf-8')
        flow.write_json(paths['edl'], {'version': 1, 'sources': {'M001': str(source)},
            'ranges': [{'source': 'M001', 'start': 0, 'end': 2, 'beat': 'SYNTHETIC'}],
            'grade': '', 'overlays': [], 'subtitles': None, 'total_duration_s': 2})
        return paths

    def approve(self, paths, stage):
        return flow.approve_stage(argparse.Namespace(project=str(paths['root']), stage=stage,
            message='SYNTHETIC TEST APPROVAL ONLY', synthetic_test=True))

    def test_preview_blocked_without_human_gate(self):
        p = self.fixture()
        with self.assertRaises(flow.FlowError):
            flow.render_project(argparse.Namespace(project=str(p['root'])))

    def test_brief_change_invalidates_strategy(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        brief = flow.read_json(p['brief'])
        brief['objective'] += ' changed'
        flow.write_json(p['brief'], brief)
        with self.assertRaises(flow.FlowError):
            flow.require_approval(p, 'strategy')

    def test_unlisted_new_media_requires_inventory(self):
        p = self.fixture()
        shutil.copyfile(self.source, p['root'] / '素材/extra.mp4')
        with self.assertRaises(flow.FlowError):
            self.approve(p, 'strategy')

    def test_changed_media_requires_inventory(self):
        p = self.fixture()
        with (p['root'] / '素材/source.mp4').open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(flow.FlowError):
            self.approve(p, 'strategy')

    def test_storyboard_requires_required_content_coverage(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        board = flow.read_json(p['board'])
        board['shots'][0]['covers'] = []
        flow.write_json(p['board'], board)
        with self.assertRaises(flow.FlowError):
            self.approve(p, 'storyboard')

    def test_missing_shot_cannot_be_approved(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        board = flow.read_json(p['board'])
        board['shots'][0]['missing'] = True
        flow.write_json(p['board'], board)
        with self.assertRaises(flow.FlowError):
            self.approve(p, 'storyboard')

    def test_frame_change_invalidates_storyboard(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        with (p['edit'] / '02_storyboard/frame.png').open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(p, 'storyboard')

    def test_edl_change_invalidates_storyboard(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        edl = flow.read_json(p['edl'])
        edl['grade'] = 'eq=contrast=1.01'
        flow.write_json(p['edl'], edl)
        with self.assertRaises(flow.FlowError):
            flow.require_approval(p, 'storyboard')

    def test_synthetic_approval_cannot_apply_to_real_project(self):
        p = self.fixture()
        state = flow.state_for(p)
        state['synthetic'] = False
        flow.write_json(p['state'], state)
        with self.assertRaises(flow.FlowError):
            self.approve(p, 'strategy')

    def test_no_audio_fails_before_render(self):
        p = self.fixture()
        shutil.copyfile(self.silent, p['root'] / '素材/source.mp4')
        manifest = flow.read_json(p['manifest'])
        manifest['sources'][0]['sha256'] = flow.sha256(p['root'] / '素材/source.mp4')
        flow.write_json(p['manifest'], manifest)
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        with self.assertRaisesRegex(flow.FlowError, '音轨'):
            flow.render_project(argparse.Namespace(project=str(p['root'])))

    def test_wrong_aspect_fails_before_render(self):
        p = self.fixture()
        brief = flow.read_json(p['brief'])
        brief['aspect_ratio'] = '9:16'
        flow.write_json(p['brief'], brief)
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        with self.assertRaisesRegex(flow.FlowError, '画幅'):
            flow.render_project(argparse.Namespace(project=str(p['root'])))

    def test_subframe_cut_is_rejected(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        edl = flow.read_json(p['edl'])
        edl['ranges'][0]['end'] = .001
        edl['total_duration_s'] = .001
        flow.write_json(p['edl'], edl)
        with self.assertRaisesRegex(flow.FlowError, '不足一个输出帧'):
            self.approve(p, 'storyboard')

    def test_unimplemented_edit_intent_is_not_silently_ignored(self):
        p = self.fixture()
        self.approve(p, 'strategy')
        original = flow.read_json(p['edl'])
        for placement in ['top', 'range', 'overlay']:
            edl = json.loads(json.dumps(original))
            if placement == 'top':
                edl['voiceover'] = 'unimplemented.wav'
            elif placement == 'range':
                edl['ranges'][0]['speed'] = 2
            else:
                edl['overlays'] = [{'file': str(self.source), 'start_in_output': 0, 'duration': 1, 'x': 20}]
            flow.write_json(p['edl'], edl)
            with self.assertRaisesRegex(flow.FlowError, '不能静默忽略'):
                self.approve(p, 'storyboard')

    def test_music_asset_change_invalidates_storyboard(self):
        p = self.fixture()
        track = p['edit'] / 'synthetic_music.mp4'
        shutil.copyfile(self.source, track)
        edl = flow.read_json(p['edl'])
        edl['music'] = {'file': 'synthetic_music.mp4', 'volume_db': -22, 'fade_out_s': .5}
        flow.write_json(p['edl'], edl)
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        with track.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(p, 'storyboard')

    def test_complete_preview_and_final_share_edl(self):
        p = self.fixture()
        edl = flow.read_json(p['edl'])
        edl['music'] = {'file': str(self.source), 'volume_db': -22, 'loop': True,
                        'fade_in_s': .2, 'fade_out_s': .4}
        flow.write_json(p['edl'], edl)
        self.approve(p, 'strategy')
        self.approve(p, 'storyboard')
        preview = flow.render_project(argparse.Namespace(project=str(p['root'])))
        with self.assertRaises(flow.FlowError):
            flow.render_project(argparse.Namespace(project=str(p['root'])), final=True)
        self.approve(p, 'preview')
        final = flow.render_project(argparse.Namespace(project=str(p['root'])), final=True)
        state = flow.state_for(p)
        self.assertEqual(state['renders']['preview']['edl_sha256'], state['renders']['final']['edl_sha256'])
        self.assertTrue(flow.read_json(Path(preview['qa']))['technical_passed'])
        self.assertTrue(flow.read_json(Path(final['qa']))['technical_passed'])
        self.assertTrue(flow.status_project(argparse.Namespace(project=str(p['root'])))['final_current'])
        # Changing a reviewed preview's bytes must invalidate approval and prohibit finalization.
        with Path(preview['file']).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(p, 'preview')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WorkflowTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'synthetic_only': True, 'tests_run': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'passed': result.wasSuccessful(), 'artifacts': str(WorkflowTests.root)}
    flow.write_json(WorkflowTests.root / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
