"""Source safety gates for the two upstream Nouveau scheduler fixes."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent / 'source/linux'

class SafetyGates(unittest.TestCase):
    def test_abi16_does_not_finalize_entity_twice(self):
        source = (ROOT/'drivers/gpu/drm/nouveau/nouveau_abi16.c').read_text()
        start = source.index('nouveau_abi16_chan_fini(')
        end = source.index('\n}', start)
        body = source[start:end]
        self.assertIn('drm_sched_entity_kill(&chan->sched->entity)', body)
        self.assertNotIn('drm_sched_entity_fini(', body)

    def test_scheduler_exposes_kill_operation(self):
        source = (ROOT/'drivers/gpu/drm/scheduler/sched_entity.c').read_text()
        self.assertIn('EXPORT_SYMBOL(drm_sched_entity_kill)', source)
        self.assertNotRegex(source, r'static\s+void\s+drm_sched_entity_kill\(')
        header = (ROOT/'include/drm/gpu_scheduler.h').read_text()
        self.assertIn('void drm_sched_entity_kill(struct drm_sched_entity *entity);', header)

if __name__ == '__main__':
    unittest.main()
