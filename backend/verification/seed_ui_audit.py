"""Prepare isolated, Echo-only UI states through the normal game workflow."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--append-vote', action='store_true')
    parser.add_argument('--only-investigation', action='store_true')
    args = parser.parse_args()
    target = args.data_dir.resolve()
    if not target.is_relative_to(ROOT / 'backend' / 'data' / 'verification'):
        raise ValueError('UI fixtures must stay in the verification data directory')
    target.mkdir(parents=True, exist_ok=True)
    os.environ['AI_MURDER_MYSTERY_DATA_DIR'] = str(target)
    os.environ['LLM_PROVIDER'] = 'echo'
    sys.path.insert(0, str(ROOT / 'backend' / 'app'))
    from main import create_app
    from workflow import GameWorkflow
    from script_catalog import ScriptCatalog

    app = create_app(target / 'app.db')
    service, store = app.state.game_service, app.state.store
    session = store.login('ui_audit_preview', 'UiAudit20261013') if args.append_vote else store.register('ui_audit_preview', 'UiAudit20261013')
    user_id = session['user']['id']
    script = json.loads((ROOT / 'backend/resources/scripts/fog_harbor_clocktower.json').read_text(encoding='utf-8'))
    for flow in script['stage_flow'].values():
        flow['investigation']['duration_seconds'] = 3600
        flow['investigation']['autonomy']['enabled'] = False
    if not args.append_vote:
        ScriptCatalog(store, service).publish(user_id, script, 'UI 验收 · 雾港档案', ['悬疑', '界面验收'])
    fixtures = json.loads((target / 'fixtures.json').read_text(encoding='utf-8'))['games'] if args.append_vote else {}

    async def command(workflow, kind, **payload):
        replies = await workflow.dispatch(str(uuid.uuid4()), {'type': kind, **payload})
        if replies[-1].get('status') != 'completed':
            raise RuntimeError(f'Fixture command failed: {kind}')

    async def end_scene(game_id, dm):
        dm.end_investigation('isolated_ui_fixture')
        service.record_responses(game_id, dm, [
            {'type': 'phase_changed', 'phase': dm.get_scene_summary()},
            {'type': 'stage_resolution', 'resolution': dm.get_stage_resolution()},
        ])

    names = ['stage_vote'] if args.append_vote else ['briefing', 'private_reveal', 'investigation', 'stage_vote', 'replay', 'legacy_investigation']
    if args.only_investigation:
        names=['investigation']
    for name in names:
        instance = copy.deepcopy(script)
        instance['script_meta']['title'] = f'UI 验收 · {name}'
        if name == 'legacy_investigation':
            game = await service.create_game(user_id, instance, 'mystery', 'deduction', 'shen_zhiwei')
            _, dm = await service.get_engine(user_id, game['id'])
            for _ in range(2):
                await dm.advance_scene_phase()
            service.record_responses(game['id'], dm, [{'type': 'phase_changed', 'phase': dm.get_scene_summary()}])
        else:
            game = store.prepare_game(user_id, instance, 'builtin:ui-fixture', 'ui-fixture-v1', workflow_config=service.workflow_defaults.model_dump())
            await service.activate_game(user_id, game['id'], 'shen_zhiwei')
            _, dm = await service.get_engine(user_id, game['id'])
            workflow = GameWorkflow(service, user_id, dm)
            if name != 'briefing':
                await command(workflow, 'advance_phase')
            if name not in {'briefing', 'private_reveal'}:
                await command(workflow, 'advance_phase')
            if name == 'investigation':
                if args.only_investigation:
                    for search_target in dm.mechanic_registry.get('search').available_targets(1,'shen_zhiwei'):
                        await command(workflow,'search',target_id=search_target['id'])
                for index in range(18):
                    store.add_notebook_entry(game_id=game['id'], role_id='shen_zhiwei', section='automatic', source_type='ui_fixture', source_key=f'ui:{index}', stage=1, title=f'阅读密度验收 · 记录 {index+1}', content='这是隔离测试记录，用于检查长文本换行、归档滚动和组件边界。' * 6)
            if name == 'stage_vote':
                await end_scene(game['id'], dm)
            if name == 'replay':
                for stage in range(1, 4):
                    if stage > 1:
                        for _ in range(2):
                            await command(workflow, 'advance_phase')
                    await end_scene(game['id'], dm)
                    await command(workflow, 'stage_vote', target_role_id='shen_zhiwei')
                    await command(workflow, 'advance_phase')
        fixtures['stage_vote_latest' if args.append_vote else name] = game['id']
        service.pause_game(user_id, game['id'])
    (target / 'fixtures.json').write_text(json.dumps({'provider': 'echo', 'paid_requests': 0, 'games': fixtures}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'provider': 'echo', 'paid_requests': 0, 'games': fixtures}))


if __name__ == '__main__':
    asyncio.run(main())
