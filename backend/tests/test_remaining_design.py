from __future__ import annotations
import asyncio
import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from main import create_app
from runtime.contracts import RuntimeAccessError
from runtime.leases import GameLeases
from runtime.workflow import GameWorkflow
from workflow_config import load_workflow_settings
from loader.script_loader import ScriptLoader

ROOT=Path(__file__).resolve().parents[2]


class RemainingDesignTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Direct unittest execution must never inherit a paid local provider.
        provider = patch.dict(os.environ, {"LLM_PROVIDER": "echo"})
        provider.start()
        self.addCleanup(provider.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(Path(self.temp.name)/'test.db')
        self.service=self.app.state.game_service; self.store=self.service.store
        self.user=self.store.register('remaining_owner','secret12')['user']['id']
        self.script=json.loads((ROOT/'backend/resources/scripts/fog_harbor_clocktower.json').read_text(encoding='utf-8'))
        self.settings=load_workflow_settings()
        self.game=self.store.prepare_game(self.user,self.script,'builtin','v',workflow_config=self.settings.model_dump())
        await self.service.activate_game(self.user,self.game['id'],'shen_zhiwei')
        _,self.dm=await self.service.get_engine(self.user,self.game['id'])
        self.workflow=GameWorkflow(self.service,self.user,self.dm)

    async def test_fixture_forces_echo_even_when_local_config_is_paid(self):
        from llm.echo import EchoLLM
        from llm.openai_compatible import OpenAICompatibleLLM
        from unittest.mock import AsyncMock
        # Reproduce the dangerous outer setting, while a network trap makes a
        # regression fail locally instead of charging the account again.
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_compatible"}), patch.object(
            OpenAICompatibleLLM, "_request", new=AsyncMock(side_effect=AssertionError("unit tests must not contact provider"))
        ) as network:
            nested = RemainingDesignTest(self._testMethodName)
            await nested.asyncSetUp()
            try:
                self.assertIsInstance(nested.service.dm_factory().llm_factory.create(), EchoLLM)
                await nested.begin_briefing()
                events = await nested.workflow.dispatch("fixture-isolation-proof", {"type": "hosting_tick"})
                self.assertTrue(any(event["type"] == "dm_host_action" for event in events))
                network.assert_not_awaited()
            finally:
                await nested.asyncTearDown()
                nested.doCleanups()

    async def asyncTearDown(self): self.temp.cleanup()

    async def investigate(self):
        for _ in range(4):
            if self.dm.state.scene_phase.value == 'investigation': break
            self.assertIn(self.dm.state.scene_phase.value, {'opening','private_reveal','briefing'})
            result = await self.workflow.dispatch(str(uuid.uuid4()),{'type':'advance_phase'})
            self.assertEqual(result[-1]['status'],'completed',result)
        self.assertEqual(self.dm.state.scene_phase.value,'investigation')

    async def begin_briefing(self):
        for _ in range(2):
            if self.dm.state.scene_phase.value == 'briefing': break
            self.assertIn(self.dm.state.scene_phase.value, {'opening','private_reveal'})
            await self.dm.advance_scene_phase()
        self.assertEqual(self.dm.state.scene_phase.value,'briefing')
        self.service.persist_engine_events(self.game['id'],self.dm)

    async def test_large_original_is_retained_paged_and_role_bound(self):
        role=self.dm.state.ai_role_ids[0]; agent=self.dm.agent_pool.get(role)
        original='档案关键词：钟楼。'+('这是一份很长的证词。'*6000)+'证词末尾哨兵_ARCHIVE_END'
        agent.remember_private_exchange(1,'对象','received',original,source_key='private-large')
        self.service.persist_engine_events(self.game['id'],self.dm)
        scope=agent.runtime_scope; archive=self.service.memory_archive
        index=archive.index(scope,1,'档案关键词')
        entry=next(row for row in index if row['source_key']=='private-large')
        chunks=[]; offset=0
        while True:
            row=archive.retrieve(scope,1,memory_id=entry['memory_id'],offset=offset)['records'][0]
            chunks.append(row['content'])
            if row['next_offset'] is None: break
            offset=row['next_offset']
        self.assertEqual(''.join(chunks),original)
        for other in [self.dm.runtime_scopes['dm'],self.dm.runtime_scopes['role:'+self.dm.state.ai_role_ids[1]]]:
            with self.assertRaises(RuntimeAccessError): archive.retrieve(other,1,memory_id=entry['memory_id'])
        await self.investigate()
        context=self.workflow.role_context(role)
        prepared=agent.prepare(context,reserved_tokens=5000)
        text=json.dumps(prepared.messages(),ensure_ascii=False)
        self.assertNotIn('ARCHIVE_END',text)
        self.assertEqual(prepared.selection['context_strategy'],'archive_retrieval')
        self.assertTrue(any(row['kind']=='testimony' for row in index))

    async def test_archive_rollback_does_not_publish_provisional_memory(self):
        role=self.dm.state.ai_role_ids[0]; agent=self.dm.agent_pool.get(role)
        agent.remember_reasoning_note(1,'PROVISIONAL_CANARY',source_key='provisional')
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.service.persist_engine_events(self.game['id'],self.dm)
                raise RuntimeError('rollback')
        self.assertEqual(self.service.memory_archive.index(agent.runtime_scope,1,'PROVISIONAL_CANARY'),[])

    async def test_other_process_lease_blocks_and_stale_run_cannot_commit(self):
        leases=self.service.leases; second=GameLeases(self.store)
        leases.claim(self.user,self.game['id'],'controller-a',self.settings)
        leases.bind(self.game['id'],self.dm.runtime_scopes['dm'].run_id)
        with self.assertRaises(RuntimeAccessError):second.claim(self.user,self.game['id'],'controller-b',self.settings)
        second.invalidate(self.user,self.game['id'])
        with self.assertRaises(RuntimeAccessError):self.service.runtime_store.assert_scope(self.dm.runtime_scopes['dm'])
        second.claim(self.user,self.game['id'],'controller-b',self.settings)
        with self.assertRaises(RuntimeAccessError):leases.heartbeat(self.game['id'],self.settings)

    async def test_crash_recovery_freezes_at_last_durable_heartbeat(self):
        await self.investigate()
        leases=self.service.leases; second=GameLeases(self.store)
        moment=time.time(); leases.claim(self.user,self.game['id'],'a',self.settings,now=moment)
        leases.bind(self.game['id'],self.dm.runtime_scopes['dm'].run_id)
        second.claim(self.user,self.game['id'],'b',self.settings,now=moment+25)
        paused=self.store.get_game(self.user,self.game['id'])
        self.assertEqual(paused['paused_at'],moment)
        self.assertEqual(paused['status'],'paused')
        self.service.sessions.pop(self.game['id'])
        with patch('game_service.time.time',return_value=moment+100): _,restored=await self.service.get_engine(self.user,self.game['id'])
        self.assertAlmostEqual(restored.state.investigation_deadline_at-self.dm.state.investigation_deadline_at,100,delta=.1)

    async def test_same_controller_reconnect_reservation(self):
        leases=self.service.leases; leases.claim(self.user,self.game['id'],'a',self.settings)
        leases.release(self.game['id'],self.settings)
        with self.assertRaises(RuntimeAccessError):leases.claim(self.user,self.game['id'],'b',self.settings)
        leases.claim(self.user,self.game['id'],'a',self.settings)

    async def test_edit_publishes_revision_and_preserves_previous_game(self):
        workshop=self.app.state.script_workshop; catalog=workshop.catalog
        original=catalog.publish(self.user,self.script,'原版',['悬疑'])
        game=self.store.prepare_game(self.user,catalog.resolve(self.user,original['catalog_id'])['script'],original['catalog_id'],original['version'])
        draft=json.loads(json.dumps(self.script)); draft['story_background']='新版本背景'
        job,_=workshop.create(self.user,'revision-test','import',{'script':draft,'title':'新版','tags':['恐怖']},original['catalog_id'])
        await workshop.execute(self.user,job['job_id'])
        self.assertEqual(workshop.job(self.user,job['job_id'])['status'],'preview')
        self.assertEqual(catalog.resolve(self.user,original['catalog_id'])['script']['script_meta']['title'],'原版')
        published=workshop.publish(self.user,job['job_id'])
        self.assertEqual(workshop.publish(self.user,job['job_id']),published)
        self.assertNotEqual(published['version'],original['version'])
        self.assertEqual(len(workshop.revisions(self.user,original['catalog_id'])),2)
        self.assertEqual(catalog.resolve(self.user,original['catalog_id'],original['version'])['script']['script_meta']['title'],'原版')
        self.assertEqual(self.store.get_game(self.user,game['id'],include_script=True)['script']['script_meta']['title'],'原版')
        other=self.store.register('other_author','secret12')['user']['id']
        with self.assertRaises(KeyError):workshop.job(other,job['job_id'])

    async def test_dm_model_hosting_is_source_bound_and_audited(self):
        await self.begin_briefing()
        result=await self.workflow.dispatch('hosting-test-0001',{'type':'hosting_tick'})
        self.assertEqual(result[-1]['status'],'completed',result)
        hosting=next(row for row in result if row['type']=='dm_host_action')
        self.assertEqual(hosting['content'],self.script['stage_flow']['stage_1']['public_briefing'])
        self.assertIn('source_key',hosting)
        with self.store._connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM model_requests WHERE actor_kind='dm'").fetchone()[0],1)

    async def test_fts_and_logs_deleted_with_game(self):
        game_id=self.game['id']; self.service.delete_game(self.user,game_id)
        with self.store._connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM memory_records WHERE game_id=?',(game_id,)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM memory_search').fetchone()[0],0)

    async def test_native_archive_loop_under_real_input_budget(self):
        await self.investigate()
        events=await self.workflow.dispatch('archive-loop-0001',{'type':'player_speech','content':'谁确认过钟楼时间线？'})
        self.assertEqual(events[-1]['status'],'completed',events)
        with self.store._connect() as c:
            models=[dict(r) for r in c.execute('SELECT * FROM model_requests')]
        self.assertTrue(any(row['actor_kind']=='role' for row in models))
        self.assertTrue(all(row['status']=='completed' for row in models),[(r['actor_role_id'],r['error']) for r in models])

    async def test_ai_draft_is_validated_and_never_automatically_published(self):
        from authoring_fixtures import FixtureAuthoringLLM
        workshop=self.app.state.script_workshop
        job,_=workshop.create(self.user,'ai-draft-0001','ai',{'topic':'密室推理','title':'AI 草稿','tags':['悬疑']})
        client = FixtureAuthoringLLM()
        with patch('llm.factory.LLMFactory.create',return_value=client):
            await workshop.execute(self.user,job['job_id'])
            completed_calls = list(client.calls)
            await workshop.execute(self.user,job['job_id'])
            self.assertEqual(client.calls,completed_calls)
            self.assertEqual(client.calls[0]['output_schema']['title'],'StoryPlan')
            self.assertEqual([item['output_schema']['title'] for item in client.calls[:6]],
                             ['StoryPlan','Opening','RoleReading','RoleReading','StageFlow','StageFlow'])
            reviews = client.calls[6:]
            self.assertTrue(all(item['output_schema']['title']=='SemanticReview' for item in reviews))
            self.assertEqual([item['stage_key'] for item in reviews if 'role_readings' in item],['stage_1','stage_2'])
            self.assertEqual(len(reviews),1+len(client.script['roles'])+client.script['script_meta']['total_stages']+1)
        draft=workshop.job(self.user,job['job_id'])
        self.assertEqual(draft['status'],'preview');self.assertIsNotNone(draft['model_request_id'])
        self.assertTrue(draft['can_publish'])
        self.assertEqual(len(workshop.catalog.list(self.user)),6)

    async def test_invalid_ai_output_keeps_failed_log_without_retry(self):
        from llm.echo import EchoLLM
        from unittest.mock import AsyncMock
        workshop=self.app.state.script_workshop
        job,_=workshop.create(self.user,'ai-failed-0001','ai',{'topic':'密室推理','title':'失败草稿','tags':['悬疑']})
        with patch.object(EchoLLM,'chat',new=AsyncMock(return_value='not json')) as call:
            await workshop.execute(self.user,job['job_id']);await workshop.execute(self.user,job['job_id'])
            self.assertEqual(call.await_count,1)
        self.assertEqual(workshop.job(self.user,job['job_id'])['status'],'failed')
        with self.assertRaises(ValueError):workshop.publish(self.user,job['job_id'])

    async def test_paged_logs_hide_private_inputs_and_opaque_reasoning(self):
        await self.begin_briefing()
        await self.workflow.dispatch('log-page-0001',{'type':'hosting_tick'})
        runtime=self.service.runtime_store
        self.assertEqual(runtime.log_page(self.user,self.game['id'],'models')['items'],[])
        self.store.update_game(self.game['id'],3,'completed','replay')
        with self.store._connect() as c:
            c.execute('UPDATE model_requests SET output_json=?',(json.dumps({'reasoning_content':'OPAQUE_SECRET','content':'公开摘要'}),))
        page=runtime.log_page(self.user,self.game['id'],'models',limit=1)
        self.assertEqual(len(page['items']),1)
        self.assertNotIn('OPAQUE_SECRET',json.dumps(page))
        self.assertEqual(runtime.log_page(self.user,self.game['id'],'models',offset=page['next_offset'])['items'],[])

    async def test_dm_input_reserves_provider_continuation_before_selecting_index(self):
        from agent.director import DMDirector
        from tools.contracts import tool_definitions
        from llm.budget import estimate_tokens
        history=[{'role':'assistant','content':'摘要','reasoning_content':'R'*16000}]
        tools=tool_definitions('dm')
        messages=DMDirector(self.dm).prepared_messages('gu_linchuan',tools,history)
        estimated=estimate_tokens([*messages,{'role':'user','content':json.dumps(tools,ensure_ascii=False)}])
        self.assertLessEqual(estimated,23000)
        self.assertEqual(messages[-1]['reasoning_content'],history[0]['reasoning_content'])

    async def test_cancelled_draft_cannot_be_published_or_reexecuted(self):
        workshop=self.app.state.script_workshop
        job,_=workshop.create(self.user,'cancel-draft-0001','import',{'script':self.script,'title':'取消草稿','tags':['悬疑']})
        workshop.cancel(self.user,job['job_id']);await workshop.execute(self.user,job['job_id'])
        self.assertEqual(workshop.job(self.user,job['job_id'])['status'],'interrupted')
        with self.assertRaises(ValueError):workshop.publish(self.user,job['job_id'])

    async def test_authoring_http_preview_restore_cancel_and_owner_boundary(self):
        import httpx
        auth=self.store.login('remaining_owner','secret12')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test',
            cookies={self.app.state.cookie_name:auth['token']},headers={'X-CSRF-Token':auth['csrf_token']}) as client:
            response=await client.post('/api/v1/authoring-jobs',json={'mode':'import','request_id':'http-authoring-0001','script':self.script,'title':'HTTP 草稿','tags':['悬疑']})
            self.assertEqual(response.status_code,202,response.text)
            job_id=response.json()['job_id']
            for _ in range(20):
                restored=(await client.get('/api/v1/authoring-jobs/'+job_id)).json()
                if restored['status']=='preview':break
                await asyncio.sleep(.01)
            self.assertEqual(restored['preview']['title'],'HTTP 草稿')
            self.assertEqual((await client.post(f'/api/v1/authoring-jobs/{job_id}/cancel')).json()['status'],'interrupted')
            self.assertEqual((await client.post(f'/api/v1/authoring-jobs/{job_id}/publish')).status_code,409)
            foreign=self.store.register('foreign_author','secret12')
            client.cookies.set(self.app.state.cookie_name,foreign['token']);client.headers['X-CSRF-Token']=foreign['csrf_token']
            self.assertEqual((await client.get('/api/v1/authoring-jobs/'+job_id)).status_code,404)
            self.assertEqual((await client.post(f'/api/v1/authoring-jobs/{job_id}/cancel')).status_code,404)

    async def test_resume_hosting_never_reexecutes_models_for_same_scene(self):
        await self.begin_briefing()
        await self.workflow.dispatch('initial-hosting-0001',{'type':'hosting_tick'})
        with self.store._connect() as c:before=c.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0]
        self.assertGreater(before,0)
        self.service.pause_game(self.user,self.game['id'])
        _,dm=await self.service.get_engine(self.user,self.game['id'])
        await GameWorkflow(self.service,self.user,dm).dispatch('resumed-hosting-0001',{'type':'hosting_tick'})
        with self.store._connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0],before)

    async def test_legacy_games_keep_existing_model_reasoning_parameters(self):
        factory=self.service.dm_factory
        def legacy_factory():
            dm=factory();create=dm.llm_factory.create
            def client():
                value=create();value.reasoning_effort='high';return value
            dm.llm_factory.create=client;return dm
        self.service.dm_factory=legacy_factory
        game=await self.service.create_game(self.user,self.script,'mystery','deduction','shen_zhiwei')
        dm=self.service.sessions[game['id']]
        self.assertFalse(dm.workflow_enabled)
        self.assertTrue(all(dm.agent_pool.get(role)._llm.reasoning_effort=='high' for role in dm.state.ai_role_ids))

if __name__=='__main__':unittest.main()
