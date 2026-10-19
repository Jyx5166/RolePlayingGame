from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from llm.base import ModelOutputTruncated
from llm.factory import LLMFactory
from llm.openai_compatible import OpenAICompatibleLLM
from script_workshop import ScriptWorkshop


class AuthoringProviderTest(unittest.IsolatedAsyncioTestCase):
    def test_authoring_effort_does_not_mutate_global_factory_or_explicit_choice(self):
        for model, configured, expected in (
            ('deepseek-v4-pro','','none'), ('deepseek-v4-pro','high','high'),
            ('other-compatible-model','',''),
        ):
            with self.subTest(model=model,configured=configured):
                factory = LLMFactory({'provider':'openai_compatible','model':model,'reasoning_effort':configured})
                workshop = object.__new__(ScriptWorkshop)
                workshop.catalog = SimpleNamespace(service=SimpleNamespace(dm_factory=lambda:SimpleNamespace(llm_factory=factory)))
                self.assertEqual(workshop._client().reasoning_effort,expected)
                self.assertEqual(factory.create().reasoning_effort,configured)

    async def test_truncated_receipt_keeps_usage_without_returning_partial_json(self):
        client = OpenAICompatibleLLM('deepseek-v4-pro','https://example.invalid','unused')
        response = {'choices':[{'finish_reason':'length','message':{'content':'{"partial":'}}],
                    'usage':{'prompt_tokens':3,'completion_tokens':8,'total_tokens':11}}
        with patch.object(client,'_request',new=AsyncMock(return_value=response)):
            with self.assertRaises(ModelOutputTruncated):
                await client.chat([{'role':'user','content':'Write a JSON object.'}])
        self.assertEqual(client.call_metadata()['finish_reason'],'length')
        self.assertEqual(client.call_metadata()['usage']['total_tokens'],11)

    def test_authoring_truncation_copy_is_actionable_and_does_not_echo_provider(self):
        error = ScriptWorkshop._safe_error(ModelOutputTruncated('private-provider-detail'))
        self.assertIn('截断',error)
        self.assertNotIn('private-provider-detail',error)

    async def test_real_adapter_sends_separate_drafting_and_review_parameters(self):
        from authoring_fixtures import FixtureAuthoringLLM
        from main import create_app
        fixture = FixtureAuthoringLLM()
        client = OpenAICompatibleLLM('deepseek-v4-pro','https://example.invalid','unused')
        payloads = []

        async def respond(payload, _headers):
            payloads.append(payload)
            output = fixture.response(json.loads(payload['messages'][-1]['content']))
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output,ensure_ascii=False)}}],
                    'usage':{'prompt_tokens':3,'completion_tokens':5,'total_tokens':8}}

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory)/'authoring.db')
            user_id = app.state.store.register('provider_check','secret12')['user']['id']
            workshop = app.state.script_workshop
            job,_ = workshop.create(user_id,'provider-parameters','ai',{'title':'参数验证','tags':[],'topic':'两人两幕'})
            with patch('llm.factory.LLMFactory.create',return_value=client), patch.object(client,'_request',side_effect=respond):
                await workshop.execute(user_id,job['job_id'])
            result = workshop.job(user_id,job['job_id'])
            self.assertEqual(result['status'],'preview',result['error'])
            self.assertTrue(result['can_publish'])
            expected_effort = ['none']*6 + ['low']*3 + ['none']*2 + ['low']
            self.assertEqual([payload['reasoning_effort'] for payload in payloads],expected_effort)
            self.assertTrue(all(payload['max_tokens']==8192 for payload in payloads))
            with app.state.store._connect() as connection:
                receipts = connection.execute('SELECT parameters_json FROM authoring_model_requests WHERE job_id=? ORDER BY created_at',(job['job_id'],)).fetchall()
            self.assertEqual([json.loads(row['parameters_json'])['reasoning_effort'] for row in receipts],expected_effort)
