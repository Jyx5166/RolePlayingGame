"""One post-patch real scheduler call, sharing the already-used 100-request ledger."""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'backend/app'))
from backend.verification.native_cycle_check import CountedNative
from backend.verification.live_game_check import RequestLedger


async def run():
    root=ROOT/'backend/data/verification/native-echo-20261013'
    raw=json.loads((root/'requests.json').read_text(encoding='utf-8'))
    if len(raw['calls'])!=99 or any(row['status']=='running' for row in raw['calls']):raise RuntimeError('只允许使用同一账本剩余的最后一个请求')
    os.environ['AI_MURDER_MYSTERY_DATA_DIR']=str(root)
    from main import create_app,build_dm
    from config import load_settings
    from workflow_config import load_workflow_settings
    from agent.director import DMDirector
    from runtime.contracts import ExecutionFrame,execution_frame
    from runtime.workflow import GameWorkflow
    from tools.contracts import tool_definitions
    from tools.gateway import ToolGateway
    settings=load_settings();ledger=RequestLedger(100,root/'requests.json');ledger.calls=raw['calls'];ledger.section='post_patch_director_dispatch'
    app=create_app(root/'app.db');service=app.state.game_service
    def factory():
        dm=build_dm()
        class Factory:
            def create(self):return CountedNative(ledger,settings,'none')
        dm.llm_factory=Factory();return dm
    service.dm_factory=factory
    user=service.store.register('focus_'+uuid.uuid4().hex[:8],uuid.uuid4().hex)['user']['id']
    script=json.loads((ROOT/'backend/resources/scripts/fog_harbor_clocktower.json').read_text(encoding='utf-8'))
    config=load_workflow_settings().model_copy(update={'model_hosting':False})
    game=service.store.prepare_game(user,script,'builtin:focus','focus',workflow_config=config.model_dump())
    await service.activate_game(user,game['id'],'shen_zhiwei');_,dm=await service.get_engine(user,game['id'])
    graph=GameWorkflow(service,user,dm)
    for _ in range(2):await graph.dispatch(str(uuid.uuid4()),{'type':'advance_phase'})
    scope=dm.runtime_scopes['dm'];frame=ExecutionFrame(game_id=game['id'],run_id=scope.run_id,request_id=str(uuid.uuid4()))
    token=execution_frame.set(frame);report={'game_id':game['id'],'maximum_total_requests':100,'automatic_retries':0}
    try:
        definitions=[row for row in tool_definitions('dm') if row['function']['name']=='select_actor']
        reply=await DMDirector(dm).call('gu_linchuan',definitions,[])
        results=[]
        for call in reply.tool_calls:
            call_id=str(uuid.uuid4());service.runtime_store.enqueue_tool(scope,call_id,frame.turn_id,frame.request_id,call.name,call.arguments,reply.model_request_id,call.provider_call_id)
            result=await ToolGateway(service,user,dm).execute(scope,call_id);results.append(result.model_dump())
        report.update(passed=any(row['status']=='succeeded' and row['data'].get('role_id') in dm.state.ai_role_ids for row in results),results=results)
    except Exception as exc:report.update(passed=False,error=str(exc).replace(settings.llm_api_key,'[REDACTED]'))
    finally:
        execution_frame.reset(token);service.pause_game(user,game['id']);report['total_requests']=len(ledger.calls)
        (root/'director-focus.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(asyncio.run(run()))
