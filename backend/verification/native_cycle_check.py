"""Actual v4 HTTP/WebSocket acceptance, durable <=100 request ledger, no retries."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(PROJECT/'backend/app'))
from backend.verification.live_game_check import RequestLedger, WireSession, FULL_GAME_SEARCH_TARGETS
from config import load_settings
from llm.openai_compatible import OpenAICompatibleLLM
from llm.echo import EchoLLM
from llm.budget import ContextBudget
import httpx
import uvicorn
import websockets


class CountedNative(OpenAICompatibleLLM):
    def __init__(self,ledger,settings,effort):
        super().__init__(settings.llm_model,settings.llm_base_url,settings.llm_api_key,settings.llm_timeout_seconds,
            budget=ContextBudget.from_config({'context_window':settings.llm_context_window,'input_limit':settings.llm_input_limit,
                'output_limit':settings.llm_output_limit,'safety_margin':settings.llm_safety_margin}),reasoning_effort=effort)
        self.ledger=ledger

    async def chat_tools(self,messages,definitions,*,transport='native_tools'):
        if transport!='native_tools':raise ValueError('本验收只使用原生函数调用，避免重复计数')
        self.reset_call_metadata()
        self.budget.validate([*messages,{'role':'user','content':json.dumps(definitions,ensure_ascii=False)}])
        record=self.ledger.reserve(messages,self.reasoning_effort,self.budget.output_limit)
        record.update(tools=definitions,transport=transport,model=self.model,temperature=.7,tool_choice='auto')
        self.ledger.save();started=time.perf_counter()
        try:
            reply=await super().chat_tools(messages,definitions,transport=transport)
            record.update(status='completed',output=reply.wire_message)
            return reply
        except asyncio.CancelledError:
            record.update(status='canceled',error='等待已取消，供应商完成和计费情况未知');raise
        except Exception as exc:
            record.update(status='failed',error=str(exc).replace(self.api_key,'[REDACTED]'));raise
        finally:
            record.update(self.call_metadata(),latency_ms=round((time.perf_counter()-started)*1000,2))
            self.ledger.save()
            print(json.dumps({key:record.get(key) for key in ('number','section','status','latency_ms','usage','error')},ensure_ascii=False),flush=True)


class NativeSession(WireSession):
    def __init__(self,http,url,game_id):
        super().__init__(http,url,game_id);self.controller=str(uuid.uuid4())
    async def connect(self):
        ticket=(await self.http.post(f'/api/v1/games/{self.game_id}/ws-ticket?controller_id={self.controller}')).raise_for_status().json()['ticket']
        count=len(self.snapshots)
        self.socket=await websockets.connect(self.url.replace('http:','ws:')+f'/ws/v1/games/{self.game_id}?ticket={ticket}&after_event_id={self.cursor}',ping_timeout=None,max_size=8000000)
        self.reader=asyncio.create_task(self._read());await self.wait(lambda:len(self.snapshots)>count,180)
    async def command(self,command,payload=None,**options):
        request_id=str(uuid.uuid4())
        events=await super().command(command,payload,terminal={'game_command_complete'},request_id=request_id,timeout=600)
        await self.wait(lambda:any(e['type']=='game_command_complete' for e in self.received.get(request_id,[])),20)
        return self.received[request_id]


async def run(args):
    settings=load_settings();root=PROJECT/'backend/data/verification'/args.name
    root.mkdir(parents=True,exist_ok=args.resume)
    os.environ['AI_MURDER_MYSTERY_DATA_DIR']=str(root)
    if args.echo:os.environ['LLM_PROVIDER']='echo'
    elif settings.llm_provider!='openai_compatible' or not settings.llm_base_url.startswith('https://api.deepseek.com'):
        raise ValueError('只允许现有 DeepSeek 配置')
    from main import create_app,build_dm
    app=create_app(root/'app.db');service=app.state.game_service
    ledger=RequestLedger(100,root/'requests.json')
    if args.resume:
        ledger.calls=json.loads((root/'requests.json').read_text(encoding='utf-8'))['calls']
        if any(row['status']=='running' for row in ledger.calls): raise ValueError('仍有运行请求，不能并发续测')
    report={'paid':not args.echo,'request_limit':100,'automatic_retries':0,'production_data_changed':False,
            'model':settings.llm_model,'reasoning_effort':args.effort or 'provider_default','checks':[],'controlled_autonomy':True,
            'fixture_changes':'仅关闭后台定时自主调度、调查时限延长为3600秒；任务、线索、角色秘密与结局保持内置剧本内容'}
    if args.resume:
        previous=json.loads((root/'report.json').read_text(encoding='utf-8'))
        report['previous_runs']=[*previous.get('previous_runs',[]),{key:previous.get(key) for key in ('game_id','completed','error','checks','reserved_requests')}]
    def save():
        report.update(reserved_requests=len(ledger.calls),statuses=dict(Counter(c['status'] for c in ledger.calls)),
            usage_totals={k:sum((c.get('usage') or {}).get(k,0) for c in ledger.calls) for k in ('prompt_tokens','completion_tokens','total_tokens')})
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,condition,**details):
        row={'id':name,'status':'PASS' if condition else 'FAIL',**details};report['checks'].append(row);save();print(json.dumps(row,ensure_ascii=False),flush=True)
    def factory():
        dm=build_dm()
        class Factory:
            def create(self):return EchoLLM() if args.echo else CountedNative(ledger,settings,args.effort)
        dm.llm_factory=Factory();return dm
    service.dm_factory=factory
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    url=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False));task=asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:await asyncio.sleep(.05)
    session=None
    try:
        async with httpx.AsyncClient(base_url=url,timeout=30,trust_env=False) as http:
            access_file=root/'access.json'
            if args.resume and access_file.exists():
                access=json.loads(access_file.read_text(encoding='utf-8'))
                registered=(await http.post('/api/v1/auth/login',json=access)).raise_for_status().json()
            else:
                access={'username':'native_qa_'+uuid.uuid4().hex[:10],'password':uuid.uuid4().hex}
                access_file.write_text(json.dumps(access),encoding='utf-8')
                registered=(await http.post('/api/v1/auth/register',json=access)).raise_for_status().json()
            http.headers['X-CSRF-Token']=registered['csrf_token'];user_id=registered['user']['id']
            script=json.loads((PROJECT/'backend/resources/scripts/fog_harbor_clocktower.json').read_text(encoding='utf-8'))
            for flow in script['stage_flow'].values():
                flow['investigation']['duration_seconds']=3600;flow['investigation']['autonomy']['enabled']=False
            published=(await http.post('/api/v1/scripts',json={'script':script,'title':'验收 · 雾港档案','tags':['悬疑','验收']})).raise_for_status().json()
            game=(await http.post('/api/v1/game-preparations',json={'catalog_id':published['catalog_id'],'version':published['version']})).raise_for_status().json()
            game_id=game['id'];report['game_id']=game_id
            await http.post(f'/api/v1/games/{game_id}/activate',json={'player_role_id':'shen_zhiwei'})
            ledger.section='initial_dm_host';session=NativeSession(http,url,game_id);await session.connect()
            check('active_model_logs_hidden',(await http.get(f'/api/v1/games/{game_id}/execution-log-pages?kind=models')).json()['items']==[])
            private_canary='PRIVATE_NATIVE_'+uuid.uuid4().hex[:8]
            for stage in range(1,4):
                ledger.section=f'stage_{stage}'
                for _ in range(2):await session.command('advance_phase')
                for target in FULL_GAME_SEARCH_TARGETS[stage]:await session.command('search',{'target_id':target})
                notebook=(await http.get(f'/api/v1/games/{game_id}/notebook')).raise_for_status().json()
                for clue in notebook['clues']:
                    if clue['stage']==stage:
                        await session.command('share_clue',{'clue_id':clue['clue_id'],'mode':'truthful','scope':'public'})
                        break
                for speech in ['请说明你亲自确认的时间线，区分事实、证词和推测。','钟楼记录与各自的证词还有哪些需要核对的矛盾？']:
                    events=await session.command('player_speech',{'content':speech})
                    check(f'stage_{stage}_role_turn',not any(e['type']=='error' for e in events),event_types=[e['type'] for e in events])
                if stage==1:
                    events=await session.command('whisper_invite',{'target_role_id':'xu_yanzhou'})
                    accepted=any(e['type']=='whisper_accepted' for e in events)
                    report['private_accepted']=accepted
                    if accepted:
                        await session.command('whisper_speech',{'content':f'本次私聊临时编号{private_canary}，不要转述。你亲眼确认过哪些细节？'})
                    before=service.store.get_runtime_snapshot(user_id,game_id)['state']['investigation_deadline_at']
                    old_scope=service.sessions[game_id].runtime_scopes['role:xu_yanzhou']
                    await session.close();await asyncio.sleep(.2);await session.connect()
                    new_scope=service.sessions[game_id].runtime_scopes['role:xu_yanzhou']
                    check('resume_independent_instances',old_scope.context_id==new_scope.context_id and old_scope.agent_instance_id!=new_scope.agent_instance_id)
                    after=service.store.get_runtime_snapshot(user_id,game_id)['state']['investigation_deadline_at']
                    check('pause_freezes_clock',after>=before)
                    if accepted:await session.command('whisper_close')
                events=await session.command('request_phase_end')
                detail=(await http.get(f'/api/v1/games/{game_id}')).raise_for_status().json()
                if detail['current_phase']!='dm_hosting':
                    report.setdefault('refused_end_votes',[]).append(stage)
                    # Controlled clock advancement, not an altered vote or a model retry.
                    # Exercise the real server timeout branch without spending an hour waiting.
                    engine=service.sessions[game_id];engine.state.investigation_deadline_at=time.time()-.1
                    service.persist_engine_events(game_id,engine)
                    count=sum(e['type']=='phase_changed' and e['payload'].get('phase',{}).get('phase')=='dm_hosting' for e in session.events)
                    await session.wait(lambda:sum(e['type']=='phase_changed' and e['payload'].get('phase',{}).get('phase')=='dm_hosting' for e in session.events)>count,240)
                    await asyncio.sleep(.1)
                    report.setdefault('controlled_clock_advances',[]).append(stage)
                # Human deliberately suspects lawyer; AI ballots remain their independent choices.
                phase=service.sessions[game_id].get_scene_summary()
                candidates=phase['resolution']['vote']['eligible_roles']
                candidate_ids=[row['role_id'] for row in candidates]
                human_target='zhou_jiming' if 'zhou_jiming' in candidate_ids else candidate_ids[0]
                events=await session.command('stage_vote',{'target_role_id':human_target})
                check(f'stage_{stage}_native_vote',not any(e['type']=='error' for e in events))
                await session.command('advance_phase')
            detail=(await http.get(f'/api/v1/games/{game_id}')).raise_for_status().json()
            check('full_three_act_game',detail['status']=='completed' and detail['current_stage']==3)
            report['ending']=next((e['payload'] for e in reversed(session.events) if e['type']=='replay'),None)
            with service.store._connect() as c:
                models=[dict(r) for r in c.execute('SELECT * FROM model_requests WHERE game_id=?',(game_id,))]
                tools=[dict(r) for r in c.execute('SELECT * FROM tool_calls WHERE game_id=?',(game_id,))]
                memories=c.execute('SELECT COUNT(*) FROM memory_records WHERE game_id=?',(game_id,)).fetchone()[0]
            check('private_not_in_dm_or_other_roles',all(private_canary not in row['input_json'] for row in models if row['actor_role_id']!='xu_yanzhou'))
            check('all_model_records_completed',all(row['status']=='completed' for row in models),failed=[{'actor':r['actor_role_id'],'error':r['error']} for r in models if r['status']!='completed'])
            report['tool_statuses']=dict(Counter(row['status'] for row in tools));report['tool_names']=dict(Counter(row['tool_name'] for row in tools))
            report['memory_records']=memories;report['model_records']=len(models)
            export=(await http.get(f'/api/v1/games/{game_id}/export')).raise_for_status().json()
            (root/'game-export.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
            check('owner_export_and_logs',len(export['records']['roles'])==4)
            report['completed']=True
    except Exception as exc:
        report.update(completed=False,error=f'{type(exc).__name__}: '+str(exc).replace(settings.llm_api_key,'[REDACTED]'));save()
        print(json.dumps({'event':'acceptance_failed','error':report['error']},ensure_ascii=False),flush=True)
    finally:
        if session:
            with contextlib.suppress(Exception):await session.close()
            (root/'wire-events.json').write_text(json.dumps(session.events,ensure_ascii=False,indent=2),encoding='utf-8')
        server.should_exit=True;await task;save()
    return 0 if report.get('completed') and all(row['status']=='PASS' for row in report['checks']) else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--name',required=True);parser.add_argument('--echo',action='store_true');parser.add_argument('--effort',default='');parser.add_argument('--resume',action='store_true')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
