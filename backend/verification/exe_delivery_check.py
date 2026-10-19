"""Final frozen-app smoke and hosting-resume idempotency; isolated Echo data only."""
import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import uuid
from pathlib import Path
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[2]


async def run():
    data=ROOT/'backend/data/verification/exe-delivery-smoke-20261013';data.mkdir(parents=True,exist_ok=False)
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    env={**os.environ,'AI_MURDER_MYSTERY_DATA_DIR':str(data),'LLM_PROVIDER':'echo','APP_PORT':str(port)}
    log=(data/'exe.log').open('w',encoding='utf-8')
    process=subprocess.Popen([str(ROOT/'dist/JujingLauncher/JujingLauncher.exe'),'--no-browser'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    report={'provider':'echo','paid_requests':0}
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',trust_env=False) as client:
            for _ in range(200):
                try:
                    if (await client.get('/health')).status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.1)
            else:raise RuntimeError('EXE 启动失败')
            auth=(await client.post('/api/v1/auth/register',json={'username':'exe_'+uuid.uuid4().hex[:8],'password':uuid.uuid4().hex})).raise_for_status().json()
            client.headers['X-CSRF-Token']=auth['csrf_token']
            script=(await client.get('/api/v1/scripts')).raise_for_status().json()[0]
            game=(await client.post('/api/v1/game-preparations',json={'catalog_id':script['catalog_id'],'version':script['version']})).raise_for_status().json();gid=game['id']
            (await client.post(f'/api/v1/games/{gid}/activate',json={'player_role_id':'shen_zhiwei'})).raise_for_status()
            async def connect():
                ticket=(await client.post(f'/api/v1/games/{gid}/ws-ticket?controller_id=exe-delivery')).raise_for_status().json()['ticket']
                ws=await websockets.connect(f'ws://127.0.0.1:{port}/ws/v1/games/{gid}?ticket={ticket}',max_size=8000000)
                while True:
                    event=json.loads(await ws.recv())
                    if event['kind']=='snapshot':return ws,event
            ws,_=await connect();events=[]
            for name,payload in [('advance_phase',{}),('advance_phase',{}),('player_speech',{'content':'请核对你亲自确认的时间线。'}),('request_phase_end',{})]:
                request=str(uuid.uuid4());await ws.send(json.dumps({'protocol_version':'1.0','kind':'command','type':name,'request_id':request,'game_id':gid,'payload':payload},ensure_ascii=False))
                while True:
                    event=json.loads(await ws.recv());events.append(event)
                    if event.get('request_id')==request and event.get('type')=='game_command_complete':break
            def model_count():
                with sqlite3.connect(data/'app.db') as connection:return connection.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0]
            before=model_count();await ws.close();await asyncio.sleep(.2)
            paused=(await client.get(f'/api/v1/games/{gid}')).raise_for_status().json()
            resumed,snapshot=await connect();after=model_count();await resumed.close()
            report.update(passed=paused['status']=='paused' and before==after and not any(e.get('type')=='error' for e in events),
                health=True,lifecycle_version=paused['lifecycle_version'],paused_on_disconnect=paused['status']=='paused',
                hosting_resume_no_extra_models=before==after,resumed_phase=snapshot['payload']['game']['phase']['phase'],
                model_attempts=after,event_types=sorted({e.get('type','') for e in events}))
    except Exception as exc:report.update(passed=False,error=str(exc))
    finally:
        if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        log.close();(ROOT/'backend/reports/exe-delivery-20261013.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(asyncio.run(run()))
