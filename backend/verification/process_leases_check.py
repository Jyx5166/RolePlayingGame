"""Two real server processes sharing SQLite; crash one, recover on the other (Echo only)."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/app'))


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));return listener.getsockname()[1]


async def run():
    data=ROOT/'backend/data/verification/process-leases-final-20261013';data.mkdir(parents=True,exist_ok=False)
    os.environ.update(AI_MURDER_MYSTERY_DATA_DIR=str(data),LLM_PROVIDER='echo')
    from main import create_app
    from workflow_config import load_workflow_settings
    app=create_app();store=app.state.store
    login={'username':'lease_qa_'+uuid.uuid4().hex[:8],'password':uuid.uuid4().hex}
    user=store.register(**login)['user']['id']
    script=json.loads((ROOT/'backend/resources/scripts/fog_harbor_clocktower.json').read_text(encoding='utf-8'))
    game=store.prepare_game(user,script,'builtin:lease','lease',workflow_config=load_workflow_settings().model_dump())
    await app.state.game_service.activate_game(user,game['id'],'shen_zhiwei')
    processes=[];streams=[];ports=[free_port(),free_port()];report={'paid_requests':0,'checks':[]}
    def check(name,value,**details):report['checks'].append({'id':name,'passed':bool(value),**details})
    try:
        for index,port in enumerate(ports):
            stream=(data/f'worker-{index}.log').open('w',encoding='utf-8');streams.append(stream)
            process=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--app-dir',str(ROOT/'backend/app'),'--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
            processes.append(process)
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{ports[0]}',trust_env=False) as first:
            for port in ports:
                for _ in range(100):
                    try:
                        if (await first.get(f'http://127.0.0.1:{port}/health')).status_code==200:break
                    except httpx.HTTPError:pass
                    await asyncio.sleep(.1)
                else:raise RuntimeError('隔离服务器启动失败')
            result=(await first.post('/api/v1/auth/login',json=login)).raise_for_status().json();first.headers['X-CSRF-Token']=result['csrf_token']
            async def connect(port,controller):
                ticket=(await first.post(f'http://127.0.0.1:{port}/api/v1/games/{game["id"]}/ws-ticket?controller_id={controller}')).raise_for_status().json()['ticket']
                return await websockets.connect(f'ws://127.0.0.1:{port}/ws/v1/games/{game["id"]}?ticket={ticket}',ping_timeout=None,max_size=8000000)
            ws=await connect(ports[0],'controller-first')
            while json.loads(await ws.recv())['kind']!='snapshot':pass
            for _ in range(2):
                request=str(uuid.uuid4());await ws.send(json.dumps({'protocol_version':'1.0','kind':'command','type':'advance_phase','request_id':request,'game_id':game['id'],'payload':{}}))
                while True:
                    event=json.loads(await ws.recv())
                    if event.get('request_id')==request and event.get('type')=='game_command_complete':break
            before=store.get_game(user,game['id'])
            with store._connect() as c:
                original=dict(c.execute('SELECT * FROM game_leases WHERE game_id=?',(game['id'],)).fetchone())
                contexts=[row['context_id'] for row in c.execute('SELECT * FROM game_context_scopes WHERE game_id=? ORDER BY scope_key',(game['id'],))]
            try:
                duplicate=await connect(ports[1],'controller-second')
                await duplicate.recv();check('other_process_rejected',False)
            except websockets.ConnectionClosed as exc:check('other_process_rejected',exc.code==4409)
            except websockets.exceptions.InvalidStatus as exc:check('other_process_rejected',exc.response.status_code==403)
            request=str(uuid.uuid4());await ws.send(json.dumps({'protocol_version':'1.0','kind':'command','type':'ask_hint','request_id':request,'game_id':game['id'],'payload':{}}))
            while True:
                event=json.loads(await ws.recv())
                if event.get('request_id')==request and event.get('type')=='game_command_complete':break
            check('first_controller_still_active',store.get_game(user,game['id'])['run_id']==before['run_id'])
            # Only the process tree launched above is terminated. No unrelated service is touched.
            subprocess.run(['taskkill','/PID',str(processes[0].pid),'/T','/F'],capture_output=True,check=True)
            check('first_process_terminated',processes[0].wait(timeout=10) is not None)
            await asyncio.sleep(load_workflow_settings().lease_seconds+1)
            recovered=await connect(ports[1],'controller-second')
            while True:
                event=json.loads(await recovered.recv())
                if event['kind']=='snapshot':break
            phase=event['payload']['game']['phase'];after=store.get_game(user,game['id'])
            with store._connect() as c:
                newer=dict(c.execute('SELECT * FROM game_leases WHERE game_id=?',(game['id'],)).fetchone())
                after_contexts=[row['context_id'] for row in c.execute('SELECT * FROM game_context_scopes WHERE game_id=? ORDER BY scope_key',(game['id'],))]
                active=c.execute("SELECT COUNT(*) FROM game_runs WHERE game_id=? AND status='active'",(game['id'],)).fetchone()[0]
            check('different_process_owns_recovery',newer['owner_id']!=original['owner_id'])
            check('single_active_run',active==1 and before['run_id']!=after['run_id'])
            check('same_game_contexts_retained',contexts==after_contexts)
            check('investigation_clock_frozen',phase['phase']=='investigation' and 590<=phase['remaining_seconds']<=600,remaining=phase['remaining_seconds'])
            await recovered.close();await asyncio.sleep(.2)
            report['passed']=all(row['passed'] for row in report['checks'])
    except Exception as exc:report.update(passed=False,error=str(exc))
    finally:
        for process in processes:
            if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        for stream in streams:stream.close()
        target=ROOT/'backend/reports/process-leases-final-20261013.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(asyncio.run(run()))
