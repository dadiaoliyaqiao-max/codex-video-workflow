"""Real tiny synthetic render; no user footage or real approval is mutated."""
import argparse
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from PIL import Image
import efficient
import flow
import test_flow


class EfficientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_flow.WorkflowTests.setUpClass()
        for name in ['root', 'source', 'frame']:
            setattr(cls, name, getattr(test_flow.WorkflowTests, name))

    def approve(self, paths, stage):
        flow.approve_stage(argparse.Namespace(project=str(paths['root']), stage=stage,
            message='SYNTHETIC EFFICIENCY TEST ONLY; NOT USER APPROVAL', synthetic_test=True))

    def test_full_pipeline_and_boundaries(self):
        p = test_flow.WorkflowTests.fixture(self)
        args = argparse.Namespace(project=str(p['root']))
        with self.assertRaises(flow.FlowError): efficient.render_preview(args)
        with self.assertRaises(flow.FlowError): efficient.render_final(args)
        # Add actual synthetic cover before approval.
        cover = p['edit'] / 'cover/synthetic.png'
        Image.new('RGB', (640, 360), '#336699').save(cover)
        flow.write_json(p['edit'] / 'cover/cover_manifest.json', {'version': 1, 'title': 'SYNTHETIC',
                        'files': [{'file': 'cover/synthetic.png'}], 'source_files': []})
        self.approve(p, 'strategy'); self.approve(p, 'storyboard')
        before = time.monotonic()
        result = efficient.render_preview(args)
        preview_seconds = time.monotonic() - before
        self.assertFalse(result['native_master_reused'])
        state = flow.state_for(p); native = state['renders']['preview']['native_master']
        self.assertEqual(flow.probe(native['file'])['streams'][0]['width'], 1920)
        self.assertEqual(flow.probe(result['file'])['streams'][0]['width'], 1280)
        with self.assertRaises(flow.FlowError): efficient.render_final(args)
        self.approve(p, 'preview')
        original_command = flow.node_command
        def no_encoding(*items):
            if items[0] in {'render', 'ffmpeg'}:
                raise AssertionError('Unchanged preview/final must not encode: ' + str(items[0]))
            return original_command(*items)
        with patch.object(flow, 'node_command', side_effect=no_encoding):
            again = efficient.render_preview(args)
            self.assertTrue(again['reused'])
            self.assertEqual(result['file'], again['file'])
            # Actual cover change invalidates preview approval, but not native picture.
            Image.new('RGB', (640, 360), '#996633').save(cover)
            with self.assertRaises(flow.FlowError): efficient.render_final(args)
            cover_only = efficient.render_preview(args)
            self.assertTrue(cover_only['reused'])
            self.approve(p, 'preview')
            # Corrupt native bytes must be caught before copying to a final.
            native_path = Path(native['file']); saved = native_path.read_bytes()
            native_path.write_bytes(saved + b'SYNTHETIC CORRUPTION')
            with self.assertRaisesRegex(flow.FlowError, '母版或检查记录'): efficient.render_final(args)
            native_path.write_bytes(saved)
            before = time.monotonic()
            final = efficient.render_final(args)
            final_seconds = time.monotonic() - before
            self.assertTrue(final['reused_native_master'])
            self.assertEqual(flow.sha256(final['file']), native['sha256'])
            self.assertEqual(flow.sha256(final['file']), flow.sha256(native['file']))
            self.assertTrue(flow.read_json(final['qa'])['reused_by_exact_byte_identity'])
            repeat = efficient.render_final(args)
            self.assertTrue(repeat['reused'])
            self.assertEqual(final['file'], repeat['file'])
        self.assertTrue(flow.status_project(args)['final_current'])
        # A changed creative input cannot reuse previously confirmed stages.
        edl = flow.read_json(p['edl']); edl['grade'] = 'eq=contrast=1.01'; flow.write_json(p['edl'], edl)
        with self.assertRaises(flow.FlowError): efficient.render_preview(args)
        with self.assertRaises(flow.FlowError): efficient.render_final(args)
        report = {'synthetic': True, 'passed': True, 'preview_render_seconds': round(preview_seconds, 3),
                  'final_copy_seconds': round(final_seconds, 3), 'real_project_performance_claim': False,
                  'checks': ['unapproved stages blocked', 'native 1920 / proxy 1280', 'unchanged preview cache hit',
                  'cover change requires approval and no video encode', 'corrupted master blocked',
                  'final byte identical without encoder', 'repeat final reused', 'EDL change invalidates approval']}
        flow.write_json(p['edit'] / 'verification.json', report)
        print(json.dumps({'verification': str(p['edit'] / 'verification.json'), **report}, ensure_ascii=False))

    def test_soundtrack_change_reuses_picture(self):
        p = test_flow.WorkflowTests.fixture(self)
        args = argparse.Namespace(project=str(p['root']))
        wave = p['edit'] / 'synthetic_mix.wav'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error', '-i', self.source,
                         '-t', '2', '-vn', '-ar', '48000', '-ac', '2', wave))
        edl = flow.read_json(p['edl'])
        edl['audio_master'] = {'file': wave.name, 'mode': 'replace'}
        flow.write_json(p['edl'], edl)
        self.approve(p, 'strategy'); self.approve(p, 'storyboard')
        efficient.render_preview(args)
        self.assertFalse(flow.state_for(p)['renders']['preview']['native_master']['picture_reused'])
        changed = p['edit'] / 'synthetic_mix_changed.wav'
        flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error', '-i', wave, '-af', 'volume=0.7', changed))
        edl['audio_master']['file'] = changed.name; flow.write_json(p['edl'], edl)
        with self.assertRaises(flow.FlowError): efficient.render_preview(args)
        self.approve(p, 'storyboard')
        old = flow.node_command
        def no_picture_encode(*items):
            if items[0] == 'render': raise AssertionError('Audio-only revision must not regenerate picture')
            return old(*items)
        with patch.object(flow, 'node_command', side_effect=no_picture_encode):
            efficient.render_preview(args)
        self.assertTrue(flow.state_for(p)['renders']['preview']['native_master']['picture_reused'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
