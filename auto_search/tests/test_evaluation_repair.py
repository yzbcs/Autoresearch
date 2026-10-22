import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_research_pipeline import evaluation, paper
import research_pipeline as pipeline


class EvaluationRepairTests(unittest.TestCase):
    def test_feedback_repair_and_id_schema(self):
        portfolio = [{'paper': paper('a'), 'idea_markdown': '# Idea A'}]
        bad = evaluation(['a'])
        bad['ranking'] = ['wrong']
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(pipeline, 'execute_json_agent', side_effect=[bad, evaluation(['a'])]) as agent:
                pipeline.evaluate_portfolio(portfolio, directory, None, 30, False)
            self.assertEqual(agent.call_count, 2)
            self.assertIn('permutation', agent.call_args.args[0])
            self.assertIn('wrong', agent.call_args.args[0])
            schema = json.loads((directory / 'evaluation.schema.json').read_text())
            self.assertEqual(schema['properties']['ranking']['items']['enum'], ['a'])

    def test_retry_limit_preserves_previous_valid_result(self):
        portfolio = [{'paper': paper('a'), 'idea_markdown': '# Idea A'}]
        bad = evaluation(['a'])
        bad['ranking'] = ['wrong']
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / 'evaluation.json'
            path.write_text(json.dumps(evaluation(['a'])))
            with patch.object(pipeline, 'execute_json_agent', return_value=bad) as agent:
                with self.assertRaisesRegex(ValueError, 'after 3 attempts'):
                    pipeline.evaluate_portfolio(portfolio, directory, None, 30, True)
            self.assertEqual(agent.call_count, 3)
            self.assertEqual(json.loads(path.read_text())['ranking'], ['a'])

    def test_cached_invalid_result_is_sent_for_repair(self):
        portfolio = [{'paper': paper('a'), 'idea_markdown': '# Idea A'}]
        bad = evaluation(['a'])
        bad['ranking'] = ['wrong']
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'evaluation.json').write_text(json.dumps(bad))
            with patch.object(pipeline, 'execute_json_agent', return_value=evaluation(['a'])) as agent:
                pipeline.evaluate_portfolio(portfolio, directory, None, 30, False)
            self.assertEqual(agent.call_count, 1)
            self.assertIn('wrong', agent.call_args.args[0])
            self.assertIn('permutation', agent.call_args.args[0])
