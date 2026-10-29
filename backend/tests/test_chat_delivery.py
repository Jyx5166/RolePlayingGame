from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from llm.echo import EchoLLM
from main import create_app
from workflow_config import WorkflowSettings


class ChatDeliveryTest(unittest.TestCase):
    def test_committed_player_receipt_streams_before_slow_dm_and_retry_does_not_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(Path(directory)/'app.db',allow_legacy_token_response=True)
            app.state.game_service.workflow_defaults=WorkflowSettings()
            with TestClient(app) as client:
                auth=client.post('/api/auth/register',json=new_test_account('stream_owner')).json()
                headers={'Authorization':'Bearer '+auth['token']}
                item=client.get('/api/v1/scripts',headers=headers).json()[0]
                game=client.post('/api/v1/game-preparations',headers=headers,json={'catalog_id':item['catalog_id'],'version':item['version']}).json()
                game_id=game['id']
                self.assertEqual(client.post(f'/api/v1/games/{game_id}/activate',headers=headers,json={'player_role_id':'shen_zhiwei'}).status_code,200)
                ticket=client.post(f'/api/v1/games/{game_id}/ws-ticket',headers=headers).json()['ticket']
                def envelope(kind,request_id,**payload):
                    return {'protocol_version':'1.0','kind':'command','type':kind,'game_id':game_id,'request_id':request_id,'payload':payload}
                def until_complete(ws):
                    events=[]
                    for _ in range(100):
                        event=ws.receive_json();events.append(event)
                        if event.get('payload',{}).get('type')=='game_command_complete':return events
                    raise AssertionError('Missing command receipt')
                with client.websocket_connect(f'/ws/v1/games/{game_id}?ticket={ticket}') as ws:
                    self.assertEqual(ws.receive_json()['kind'],'snapshot')
                    for _ in range(4):
                        phase=app.state.game_service.sessions[game_id].state.scene_phase.value
                        if phase=='investigation':break
                        self.assertIn(phase,{'opening','private_reveal','briefing'})
                        ws.send_json(envelope('advance_phase',str(uuid.uuid4())))
                        until_complete(ws)
                    self.assertEqual(app.state.game_service.sessions[game_id].state.scene_phase.value,'investigation')
                    first_returned=False
                    invocations=0
                    original=EchoLLM.chat_tools
                    async def delayed(model,*args,**kwargs):
                        nonlocal first_returned,invocations
                        invocations+=1
                        if invocations==1:
                            await asyncio.sleep(.6)
                            first_returned=True
                        return await original(model,*args,**kwargs)
                    request_id=str(uuid.uuid4())
                    command=envelope('player_speech',request_id,content='周既明，请回应当前公开信息。')
                    with patch.object(EchoLLM,'chat_tools',new=delayed):
                        ws.send_json(command)
                        observed=[]
                        for _ in range(30):
                            event=ws.receive_json();observed.append(event)
                            if event.get('payload',{}).get('type')=='human_speech_echo':
                                self.assertEqual(event['request_id'],request_id)
                                self.assertFalse(first_returned,'The receipt must arrive while the DM model is still waiting')
                                break
                        else:self.fail('No player receipt')
                        observed.extend(until_complete(ws))
                        self.assertEqual(sum(e.get('payload',{}).get('type')=='human_speech_echo' for e in observed),1)
                        self.assertTrue(any(e.get('payload',{}).get('role_id')=='zhou_jiming' for e in observed))
                        before=invocations
                        ws.send_json(command)
                        repeated=until_complete(ws)
                        self.assertTrue(any(e.get('payload',{}).get('type')=='human_speech_echo' for e in repeated))
                        self.assertEqual(invocations,before)
