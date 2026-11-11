"""Synthetic-only Hypit integration verification; no model/API calls.

Hypit's cut command publishes using a local hardlink. A restricted sandbox may
require explicit tool escalation for this optional command's verification.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flow
import hypit_reference as hypit


class HypitReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = HERE / '_verification' / ('hypit_reference_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        cls.output.mkdir(parents=True)
        cls.source = cls.output / 'SYNTHETIC_pattern.mp4'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24:duration=3',
            '-f', 'lavfi', '-i', 'sine=frequency=550:sample_rate=48000:duration=3',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', cls.source))
        cls.checks = []

    def fixture(self, name, reference=True):
        project = self.output / name
        flow.init_project(argparse.Namespace(project=str(project), name=name, synthetic=True))
        paths = flow.project_paths(project)
        source = project / '素材/source.mp4'
        shutil.copyfile(self.source, source)
        row = {'id': 'M001', 'kind': 'video', 'path': str(source), 'sha256': flow.sha256(source),
               'duration': 3.0, 'width': 640, 'height': 360, 'has_audio': True}
        references = []
        if reference:
            ref = project / '参考视频/SYNTHETIC_reference.mp4'
            shutil.copyfile(self.source, ref)
            references = [{**row, 'id': 'R001', 'path': str(ref), 'sha256': flow.sha256(ref)}]
        flow.write_json(paths['manifest'], {'schema_version': 1, 'sources': [row], 'references': references})
        brief = flow.read_json(paths['brief'])
        brief.update(objective='Hypit 合成证据集成测试，不是真实剪辑要求', target_duration_s=2,
                     aspect_ratio='16:9', fps='24')
        flow.write_json(paths['brief'], brief)
        paths['strategy'].write_text('Synthetic-only test. Inspect the generated test pattern and preserve its time ordering. '
            'This fixture verifies local media evidence, hash binding and approval invalidation. '
            'It does not represent a real user commission, semantic video assessment, transcription or human approval.', encoding='utf-8')
        if reference:
            paths['reference_analysis'].write_text('Synthetic reference analysis. The reference is the explicitly generated color/motion test pattern. '
                'No speech or story interpretation is claimed. Hypit overview evidence must still be collected before this test-only strategy can be recorded.', encoding='utf-8')
            (paths['strategy'].parent / 'ANALYSIS.md').write_text('Synthetic test-pattern reading only; no story or speech claim.', encoding='utf-8')
            (paths['strategy'].parent / 'TIMELINE.md').write_text('0–3 seconds: generated moving color test pattern.', encoding='utf-8')
        return paths

    def approve(self, paths):
        flow.approve_stage(argparse.Namespace(project=str(paths['root']), stage='strategy',
            message='SYNTHETIC TEST ONLY; not a human approval', synthetic_test=True))

    def test_reference_evidence_and_stale_guards(self):
        paths = self.fixture('中文参考测试')
        manifest = flow.read_json(paths['manifest'])
        with self.assertRaises(flow.FlowError):
            self.approve(paths)
        self.checks.append('Video-reference strategy is blocked before actual Hypit evidence')
        result = hypit.prepare_reference(paths['root'])
        self.assertEqual(result['version'], '0.3.1')
        proof_path = Path(result['manifest'])
        proof = flow.read_json(proof_path)
        commands = proof['references'][0]['commands']
        self.assertEqual({c['name'] for c in commands}, {'probe', 'boundaries', 'tile'})
        self.assertTrue(hypit.validate_reference_evidence(paths['root'], manifest)['files'])
        for command in commands:
            for output in command['outputs']:
                self.assertTrue((paths['edit'] / output['path']).is_file())
        self.checks.append('Real Hypit probe, boundaries and tile outputs exist and match hashes')
        extra = paths['edit'] / proof['run'] / 'additional_commands'
        extra.mkdir()
        ref_source = Path(manifest['references'][0]['path'])
        frames, _ = hypit.record_command(paths['edit'], extra, 'frames',
            ['media', 'frames', ref_source, '--at', '0.5,1.5', '--label-time', '--to', extra / 'frames'], [extra / 'frames'])
        cut, _ = hypit.record_command(paths['edit'], extra, 'cut',
            ['media', 'cut', ref_source, '--start', '1', '--end', '2', '--label-time', '--to', extra / 'clip.mp4'], [extra / 'clip.mp4'])
        flow.run_capture(flow.node_command('ffmpeg', '-v', 'error', '-i', extra / 'clip.mp4', '-f', 'null', '-'))
        proof['details'].append({'id': 'R001', 'input_sha256': manifest['references'][0]['sha256'],
                                 'start': .5, 'end': 2, 'commands': [frames, cut]})
        flow.write_json(proof_path, proof)
        self.checks.append('Real Hypit timestamped frames and cut exports exist; cut fully decodes')
        self.approve(paths)
        flow.require_approval(paths, 'strategy')
        analysis = paths['strategy'].parent / 'ANALYSIS.md'
        original_analysis = analysis.read_text(encoding='utf-8')
        analysis.write_text(original_analysis + '\nChanged detailed interpretation.', encoding='utf-8')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'strategy')
        analysis.write_text(original_analysis, encoding='utf-8')
        flow.require_approval(paths, 'strategy')
        self.checks.append('Changing detailed ANALYSIS.md invalidates strategy approval')
        detail = hypit.detail_reference(paths['root'], 'R001', .5, 1.0)
        self.assertGreater(detail['grids'], 0)
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'strategy')
        self.checks.append('Real Hypit every-frame detail changes evidence and invalidates prior strategy approval')
        self.approve(paths)
        proof = flow.read_json(proof_path)
        grid = next(item for command in proof['references'][0]['commands'] if command['name'] == 'tile'
                    for item in command['outputs'] if item['path'].endswith('.jpg'))
        grid_path = paths['edit'] / grid['path']
        original = grid_path.read_bytes()
        grid_path.write_bytes(original + b'changed')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'strategy')
        grid_path.write_bytes(original)
        flow.require_approval(paths, 'strategy')
        self.checks.append('Changed reference-evidence image invalidates approval')
        ref = Path(manifest['references'][0]['path'])
        ref.write_bytes(ref.read_bytes() + b'changed')
        with self.assertRaises(flow.FlowError):
            flow.require_approval(paths, 'strategy')
        self.checks.append('Changed reference bytes invalidate evidence and approval')

    def test_no_reference_remains_compatible(self):
        paths = self.fixture('无参考兼容测试', reference=False)
        self.approve(paths)
        flow.require_approval(paths, 'strategy')
        self.assertFalse((paths['edit'] / 'analysis/hypit/manifest.json').exists())
        self.checks.append('No-reference workflows need no Hypit evidence and preserve existing gate behavior')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HypitReferenceTests))
    report = {'synthetic_only': True, 'tests_run': result.testsRun, 'passed': result.wasSuccessful(),
              'errors': len(result.errors), 'failures': len(result.failures),
              'checks': HypitReferenceTests.checks, 'artifacts': str(HypitReferenceTests.output),
              'cloud_calls': 0, 'real_user_approvals': 0}
    flow.write_json(HypitReferenceTests.output / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
