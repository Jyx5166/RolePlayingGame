"""Owner-scoped durable drafts, explicit publication, and immutable revisions."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from pydantic import ValidationError

from authoring_pipeline import AuthoringDesignError, AuthoringPipeline, COMMON_PROMPT
from authoring_validation import inspect_authoring
from llm.budget import ContextBudgetError
from llm.base import ModelOutputTruncated
from llm.openai_compatible import OpenAICompatibleLLM
from script_catalog import script_version
from storage import utc_now
from security import validate_script_payload


class AuthoringInterrupted(Exception):
    pass


class ScriptWorkshop:
    def __init__(self, catalog):
        self.catalog, self.store = catalog, catalog.store
        self.generation_lock = asyncio.Lock()
        with self.store._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS script_revisions (
                  catalog_id TEXT NOT NULL, version TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
                  script_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(catalog_id,version));
                CREATE TABLE IF NOT EXISTS authoring_jobs (
                  job_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                  request_id TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, catalog_id TEXT,
                  input_json TEXT NOT NULL, draft_json TEXT, preview_json TEXT, result_json TEXT,
                  model_request_id TEXT, model_status TEXT, model_input_json TEXT, model_output TEXT,
                  usage_json TEXT, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  UNIQUE(user_id,request_id));
                CREATE TABLE IF NOT EXISTS authoring_steps (
                  job_id TEXT NOT NULL REFERENCES authoring_jobs(job_id) ON DELETE CASCADE,
                  step_id TEXT NOT NULL, ordinal INTEGER NOT NULL, label TEXT NOT NULL,
                  status TEXT NOT NULL, output_json TEXT, error TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  PRIMARY KEY(job_id,step_id));
                CREATE TABLE IF NOT EXISTS authoring_model_requests (
                  request_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES authoring_jobs(job_id) ON DELETE CASCADE,
                  step_id TEXT NOT NULL, status TEXT NOT NULL, input_json TEXT NOT NULL,
                  output_text TEXT, provider TEXT, model TEXT, provider_invoked INTEGER,
                  finish_reason TEXT, usage_json TEXT, duration_ms INTEGER, parameters_json TEXT,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            ''')
            connection.execute('''INSERT OR IGNORE INTO script_revisions
                SELECT catalog_id,version,user_id,script_json,created_at FROM published_scripts''')
            if 'parameters_json' not in {row['name'] for row in connection.execute('PRAGMA table_info(authoring_model_requests)')}:
                connection.execute('ALTER TABLE authoring_model_requests ADD COLUMN parameters_json TEXT')
            # A process restart cannot know whether an outstanding provider call
            # was charged. Keep its receipt and partial draft, never auto-resume.
            connection.execute("""UPDATE authoring_steps SET status='interrupted',
                error='服务重启，步骤未完成；已保留草稿，不会自动重跑',updated_at=?
                WHERE status IN ('running','pending') AND job_id IN
                (SELECT job_id FROM authoring_jobs WHERE status IN ('queued','generating','validating'))""", (utc_now(),))
            connection.execute("UPDATE authoring_model_requests SET status='interrupted',updated_at=? WHERE status='running'", (utc_now(),))
            connection.execute("""UPDATE authoring_jobs SET status='interrupted',model_status=CASE
                WHEN model_status='running' THEN 'interrupted' ELSE model_status END,
                error='服务重启，创作已中断；已保留完成步骤，不会自动重跑模型',updated_at=?
                WHERE status IN ('queued','generating','validating')""", (utc_now(),))

    def job(self, user_id, job_id):
        with self.store._connect() as connection:
            row = connection.execute('SELECT * FROM authoring_jobs WHERE user_id=? AND job_id=?',(user_id,job_id)).fetchone()
        if not row: raise KeyError('创作任务不存在')
        result = dict(row)
        for name in ('input','draft','preview','result','usage'):
            raw = result.pop(name+'_json')
            result[name] = json.loads(raw) if raw else None
        result.pop('model_input_json'); result.pop('model_output')
        with self.store._connect() as connection:
            result['steps'] = [dict(step) for step in connection.execute(
                'SELECT step_id,label,status,error FROM authoring_steps WHERE job_id=? ORDER BY ordinal', (job_id,))]
            # Older tasks checkpointed only after the entire review. Recover
            # their completed reports for truthful display after interruption.
            preview = result.get('preview') or {}
            review_steps = [step for step in result['steps'] if step['step_id'].startswith('review:')]
            if preview.get('semantic_review',{}).get('status') == 'not_run' and any(step['status']=='completed' for step in review_steps):
                reports = connection.execute("SELECT step_id,output_json FROM authoring_steps WHERE job_id=? AND step_id LIKE 'review:%' AND status='completed' ORDER BY ordinal",(job_id,)).fetchall()
                summaries, issues = [], []
                for row in reports:
                    report = json.loads(row['output_json'] or '{}')
                    if report.get('summary'):
                        summaries.append(report['summary'])
                    for issue in report.get('issues',[]):
                        issue['path'] = AuthoringPipeline._review_path(row['step_id'][7:].removesuffix(':recheck'),issue['path'],result['draft'])
                        issues.append(issue)
                preview['semantic_review'] = {'status':'running' if result['status'] in {'generating','validating'} else 'incomplete',
                    'summary':'\n'.join(summaries),'issues':issues,'method':'model_review',
                    'completed_scopes':len(reports),'total_scopes':len(review_steps)}
        result['can_publish'] = self._can_publish(result)
        return result

    def _can_publish(self, job):
        if job['status'] != 'preview' or not job['draft']:
            return False
        preview = job.get('preview') or {}
        checks = preview.get('authoring_validation')
        if checks is not None and not checks.get('passed'):
            return False
        if job['mode'] == 'ai' or preview.get('semantic_required') or (
            job.get('catalog_id') and self.source_job_for_catalog(job['user_id'],job['catalog_id'])
        ):
            return bool(checks and checks.get('passed') and preview.get('semantic_review', {}).get('status') == 'passed')
        return True

    def source_job_for_catalog(self, user_id, catalog_id):
        """Keep AI review requirements when editing a published catalog entry.

        Older publication code stored a synthetic receipt ID. Recover those
        entries from owner-scoped published job results, including AI revisions.
        An intervening plain import cannot erase the AI design lineage.
        """
        with self.store._connect() as connection:
            item = connection.execute('SELECT authoring_job_id FROM published_scripts WHERE user_id=? AND catalog_id=?',
                                      (user_id,catalog_id)).fetchone()
            if not item:
                return None
            rows = connection.execute("SELECT job_id,mode,preview_json,result_json FROM authoring_jobs WHERE user_id=? AND status='published' ORDER BY created_at DESC",
                                      (user_id,)).fetchall()
        for row in rows:
            result = json.loads(row['result_json'] or '{}')
            if row['job_id'] != item['authoring_job_id'] and result.get('catalog_id') != catalog_id:
                continue
            if row['mode'] == 'ai' or json.loads(row['preview_json'] or '{}').get('semantic_required'):
                return row['job_id']
        return None

    def create(self, user_id, request_id, mode, input_data, catalog_id=None):
        input_data = {key:value for key,value in input_data.items() if key != 'source_job_id' or value is not None}
        if catalog_id and self.catalog.resolve(user_id,catalog_id)['source']!='imported':
            raise ValueError('内置剧本请先导入为自己的版本')
        catalog_source = self.source_job_for_catalog(user_id,catalog_id) if catalog_id and mode == 'import' else None
        if catalog_source:
            input_data['source_job_id'] = catalog_source
        if input_data.get('source_job_id'):
            source = self.job(user_id,input_data['source_job_id'])
            if mode != 'import' or not source.get('draft'):
                raise ValueError('修订任务需要已有草稿，新的 AI 创作请使用新主题')
        with self.store.transaction() as connection:
            row = connection.execute('SELECT * FROM authoring_jobs WHERE user_id=? AND request_id=?',(user_id,request_id)).fetchone()
            if row:
                previous_input = json.loads(row['input_json'])
                # Replaying a completed revision keeps its original design,
                # even if publication has since advanced the catalog lineage.
                if catalog_source and previous_input.get('source_job_id'):
                    input_data['source_job_id'] = previous_input['source_job_id']
                if previous_input!=input_data or row['mode']!=mode or row['catalog_id']!=catalog_id:
                    raise ValueError('同一任务请求编号不能对应不同内容')
                return self.job(user_id,row['job_id']),False
            job_id = str(uuid.uuid4())
            connection.execute('''INSERT INTO authoring_jobs(job_id,user_id,request_id,mode,status,catalog_id,input_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',(job_id,user_id,request_id,mode,'queued',catalog_id,json.dumps(input_data,ensure_ascii=False),utc_now(),utc_now()))
            self._step(job_id, 'plan' if mode == 'ai' else 'validation',
                       '故事设计与真相' if mode == 'ai' else '结构与线索校验', 'pending')
        return self.job(user_id,job_id),True

    def update(self, job_id, **fields):
        columns = {**fields,'updated_at':utc_now()}
        with self.store._connect() as connection:
            connection.execute('UPDATE authoring_jobs SET '+','.join(key+'=?' for key in columns)+' WHERE job_id=?',(*columns.values(),job_id))

    def _active(self, user_id, job_id):
        if self.job(user_id, job_id)['status'] not in {'generating', 'validating'}:
            raise AuthoringInterrupted()

    def _client(self):
        client = self.catalog.service.dm_factory().llm_factory.create()
        # The reasoning budget shares max_tokens with the JSON answer. Use
        # direct structured drafting and a separate reasoning review, without
        # changing global settings or an explicitly configured effort level.
        if isinstance(client,OpenAICompatibleLLM) and client.model.startswith('deepseek-v4') and not client.reasoning_effort:
            client.reasoning_effort = 'none'
            client.authoring_default_effort = True
        return client

    def _source_plan(self, user_id, source_job_id):
        source = self.job(user_id,source_job_id)
        with self.store._connect() as connection:
            row = connection.execute("SELECT output_json FROM authoring_steps WHERE job_id=? AND step_id='plan'",(source_job_id,)).fetchone()
        if row and row['output_json']:
            return json.loads(row['output_json'])
        if source['mode'] == 'ai' or (source.get('preview') or {}).get('semantic_required'):
            raise AuthoringDesignError('原 AI 草稿缺少完整故事设计，请重新创作，不能跳过审稿发布')
        return None

    def _step(self, job_id, step_id, label, status, *, output=None, error=''):
        with self.store._connect() as connection:
            ordinal = connection.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM authoring_steps WHERE job_id=?', (job_id,)).fetchone()[0]
            connection.execute('''INSERT INTO authoring_steps
                (job_id,step_id,ordinal,label,status,output_json,error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id,step_id) DO UPDATE SET label=excluded.label,status=excluded.status,
                output_json=COALESCE(excluded.output_json,authoring_steps.output_json),error=excluded.error,updated_at=excluded.updated_at''',
                (job_id, step_id, ordinal, label, status, json.dumps(output,ensure_ascii=False) if output is not None else None, error, utc_now(), utc_now()))

    @staticmethod
    def _safe_error(exc):
        if isinstance(exc, ValidationError):
            paths = ['.'.join(str(part) for part in item['loc']) for item in exc.errors(include_input=False,include_url=False)[:5]]
            return '生成内容不符合约定格式，请修订后重新校验：' + '、'.join(paths)
        if isinstance(exc, json.JSONDecodeError):
            return '模型没有返回有效 JSON，已保留完成的步骤；本次不会自动重试'
        if isinstance(exc, (AuthoringDesignError, ContextBudgetError)):
            return str(exc)[:600]
        if isinstance(exc, ModelOutputTruncated):
            return '当前步骤的模型输出被截断，不能作为有效草稿；请缩小创作范围或调整模型输出预算后重试'
        return '模型调用或创作步骤未完成；已保留完成的步骤，请检查模型配置后重试'

    def _preview(self, draft):
        meta = draft.get('script_meta') if isinstance(draft.get('script_meta'),dict) else {}
        roles = draft.get('roles') if isinstance(draft.get('roles'),list) else []
        return {'script_id':meta.get('script_id',''), 'title':meta.get('title',''),
                'total_stages':meta.get('total_stages',0), 'role_count':len(roles),
                'ai_agent_count':max(0,len(roles)-1),
                'supported_modes':meta.get('supported_skills',[]),
                'playable_roles':[{'role_id':role.get('role_id',''),'role_name':role.get('role_name',''),
                                   'public_identity':role.get('public_identity','')} for role in roles if isinstance(role,dict) and role.get('human_playable')],
                'story_background':draft.get('story_background','')}

    def _checkpoint(self, user_id, job_id, draft, plan, checks, review):
        with self.store.transaction():
            self._active(user_id, job_id)
            validate_script_payload(draft)
            preview = self._preview(draft)
            preview['semantic_required'] = plan is not None
            previous_preview = self.job(user_id,job_id).get('preview') or {}
            if checks is None and 'authoring_validation' in previous_preview:
                preview['authoring_validation'] = previous_preview['authoring_validation']
            if checks is not None:
                preview['authoring_validation'] = checks
            if review is not None:
                preview['semantic_review'] = review
            self.update(job_id,draft_json=json.dumps(draft,ensure_ascii=False),preview_json=json.dumps(preview,ensure_ascii=False))
            if plan:
                self._step(job_id,'plan','故事设计与真相','completed',output=plan)
                pending = []
                if self.job(user_id,job_id)['mode'] == 'ai':
                    pending.append(('opening','独立开幕'))
                    pending.extend((f"role:{role['role_id']}",f"角色本 · {role['role_name']}") for role in plan['roles'])
                    pending.extend((f'stage:stage_{stage}',f'第 {stage} 幕') for stage in range(1,plan['script_meta']['total_stages']+1))
                pending.extend([('validation','结构与线索校验'),('review:public','开幕与分幕审稿')])
                pending.extend((f"review:role:{role['role_id']}",f"角色审稿 · {role['role_name']}") for role in plan['roles'])
                pending.extend((f'review:cross:stage_{stage}',f'第 {stage} 幕角色交叉核对') for stage in range(1,plan['script_meta']['total_stages']+1))
                pending.append(('review:logic','时间线与证据链审稿'))
                with self.store._connect() as connection:
                    for step_id,label in pending:
                        if not connection.execute('SELECT 1 FROM authoring_steps WHERE job_id=? AND step_id=?',(job_id,step_id)).fetchone():
                            self._step(job_id,step_id,label,'pending')

    def _inspect(self, user_id, job_id, draft, plan):
        self._active(user_id,job_id)
        self.update(job_id,status='validating')
        self._step(job_id,'validation','结构与线索校验','running')
        report = inspect_authoring(draft,plan)
        self._step(job_id,'validation','结构与线索校验','completed' if report['passed'] else 'failed',
                   output=report,error='' if report['passed'] else '结构或线索校验未通过，请查看校验报告')
        return report

    async def _call_model(self, user_id, job_id, client, step_id, label, prompt, payload, model):
        self._active(user_id,job_id)
        if getattr(client,'authoring_default_effort',False):
            # Cross-role manuscripts are already supplied verbatim. Direct
            # comparison avoids spending the bounded JSON output on reasoning.
            client.reasoning_effort = 'low' if step_id.startswith('review:') and not step_id.startswith('review:cross:') else 'none'
        self.update(job_id,status='validating' if step_id.startswith('review:') else 'generating')
        self._step(job_id,step_id,label,'running')
        messages = [{'role':'system','content':COMMON_PROMPT + '\n' + prompt},
                    {'role':'user','content':json.dumps({**payload,'output_schema':model.model_json_schema()},ensure_ascii=False)}]
        request_id, started = str(uuid.uuid4()), time.monotonic()
        with self.store.transaction() as connection:
            self._active(user_id,job_id)
            connection.execute('''INSERT INTO authoring_model_requests
                (request_id,job_id,step_id,status,input_json,parameters_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)''',
                (request_id,job_id,step_id,'running',json.dumps(messages,ensure_ascii=False),
                 json.dumps({key:value for key,value in client.call_metadata().items() if key in {'reasoning_effort','output_limit','timeout_seconds'}},ensure_ascii=False),
                 utc_now(),utc_now()))
            self.update(job_id,model_request_id=request_id,model_status='running')
        client.reset_call_metadata()
        raw, status = None, 'failed'
        try:
            self._active(user_id,job_id)
            raw = await client.chat(messages)
            self._active(user_id,job_id)
            text = raw.strip()
            if text.startswith('```json\n') and text.endswith('```'):
                text = text[8:-3].strip()
            output = model.model_validate(json.loads(text)).model_dump(exclude_none=True)
            self._step(job_id,step_id,label,'completed',output=output)
            status = 'completed'
            return output
        except (asyncio.CancelledError, AuthoringInterrupted):
            status = 'interrupted'
            self._step(job_id,step_id,label,'interrupted',error='步骤已中断，完成的内容已保留')
            raise
        except Exception as exc:
            self._step(job_id,step_id,label,'failed',error=self._safe_error(exc))
            raise
        finally:
            metadata = client.call_metadata()
            usage = metadata.get('usage')
            with self.store.transaction() as connection:
                connection.execute('''UPDATE authoring_model_requests SET status=?,output_text=?,provider=?,model=?,
                    provider_invoked=?,finish_reason=?,usage_json=?,duration_ms=?,updated_at=? WHERE request_id=?''',
                    (status,raw,metadata.get('provider'),metadata.get('model'),metadata.get('provider_invoked'),
                     metadata.get('finish_reason'),json.dumps(usage) if usage is not None else None,
                     round((time.monotonic()-started)*1000),utc_now(),request_id))
                receipts = connection.execute('SELECT usage_json FROM authoring_model_requests WHERE job_id=?',(job_id,)).fetchall()
                total_usage = None
                if receipts and all(receipt['usage_json'] is not None for receipt in receipts):
                    total_usage = {}
                    for receipt in receipts:
                        for key,value in json.loads(receipt['usage_json']).items():
                            if isinstance(value,int) and not isinstance(value,bool):
                                total_usage[key] = total_usage.get(key,0) + value
                self.update(job_id,model_status=status,usage_json=json.dumps(total_usage) if total_usage is not None else None)

    async def execute(self, user_id, job_id):
        job = self.job(user_id,job_id)
        if job['status']!='queued': return
        with self.store.transaction() as connection:
            if not connection.execute("UPDATE authoring_jobs SET status=?,updated_at=? WHERE job_id=? AND status='queued'",
                ('validating' if job['mode']=='import' else 'generating',utc_now(),job_id)).rowcount: return
        try:
            values = job['input']
            draft = values.get('script')
            if job['mode']=='ai':
                async with self.generation_lock:
                    self._active(user_id,job_id)
                    client = self._client()
                    pipeline = AuthoringPipeline(
                        lambda step,label,prompt,payload,model: self._call_model(user_id,job_id,client,step,label,prompt,payload,model),
                        lambda draft,plan,checks,review: self._checkpoint(user_id,job_id,draft,plan,checks,review),
                        lambda draft,plan: self._inspect(user_id,job_id,draft,plan))
                    draft,plan,checks,review = await pipeline.run(values)
            else:
                self._active(user_id,job_id)
                validate_script_payload(draft)
                if isinstance(draft.get('script_meta'),dict):
                    draft['script_meta'].update(title=values['title'].strip(),tags=values['tags'])
                plan = self._source_plan(user_id,values['source_job_id']) if values.get('source_job_id') else None
                checks = self._inspect(user_id,job_id,draft,plan)
                review = {'status':'not_run','summary':'导入仅执行结构与线索校验，未进行模型审稿。','issues':[]}
                self._checkpoint(user_id,job_id,draft,plan,checks,review)
                if plan is not None and checks['passed']:
                    async with self.generation_lock:
                        self._active(user_id,job_id)
                        client = self._client()
                        pipeline = AuthoringPipeline(
                            lambda step,label,prompt,payload,model: self._call_model(user_id,job_id,client,step,label,prompt,payload,model),
                            lambda draft,plan,checks,review: self._checkpoint(user_id,job_id,draft,plan,checks,review),
                            lambda draft,plan: self._inspect(user_id,job_id,draft,plan))
                        review = await pipeline.review(draft,plan)
                        self._checkpoint(user_id,job_id,draft,plan,checks,review)
            with self.store.transaction():
                self._active(user_id,job_id)
                validate_script_payload(draft)
                passed = checks['passed'] and (plan is None or review['status'] == 'passed')
                if passed:
                    self.catalog.service.inspect_script(draft,'deduction')
                self.update(job_id,status='preview' if passed else 'failed',
                            error='' if passed else '剧本校验未通过；已保存草稿和问题报告，请修订后重新校验')
        except AuthoringInterrupted:
            return
        except asyncio.CancelledError:
            self.update(job_id,status='interrupted',error='执行已中断，未发布；不会自动再次调用模型')
            raise
        except Exception as exc:
            if self.job(user_id,job_id)['status'] in {'generating','validating'}:
                error = self._safe_error(exc)
                with self.store.transaction() as connection:
                    latest = connection.execute("SELECT step_id,label,status FROM authoring_steps WHERE job_id=? ORDER BY updated_at DESC LIMIT 1",(job_id,)).fetchone()
                    failed_step = connection.execute("SELECT 1 FROM authoring_steps WHERE job_id=? AND status='failed' LIMIT 1",(job_id,)).fetchone()
                    if not failed_step and latest and latest['status'] in {'running','completed'}:
                        self._step(job_id,latest['step_id'],latest['label'],'failed',error=error)
                    self.update(job_id,status='failed',error=error)

    def cancel(self,user_id,job_id):
        with self.store.transaction():
            job=self.job(user_id,job_id)
            if job['status']=='published':raise ValueError('已发布版本不能作为草稿取消')
            self.update(job_id,status='interrupted',error='创作已取消，原始任务记录保留；不会自动重跑模型')
            with self.store._connect() as connection:
                connection.execute("UPDATE authoring_steps SET status='interrupted',error='任务已取消',updated_at=? WHERE job_id=? AND status IN ('pending','running')",(utc_now(),job_id))
        return self.job(user_id,job_id)

    def publish(self, user_id, job_id):
        with self.store.transaction() as connection:
            job = self.job(user_id,job_id)
            if job['status']=='published': return job['result']
            if not self._can_publish(job): raise ValueError('剧本尚未通过必要校验，不能发布')
            script = job['draft']
            validate_script_payload(script)
            self.catalog.service.inspect_script(script,'deduction')
            if job['catalog_id']:
                catalog_id = job['catalog_id']
                current = self.catalog.resolve(user_id,catalog_id)
                version = script_version(script)
                result = {**self.catalog.public_item({**current,'script':script,'version':version}),'authoring_job_id':job_id}
                connection.execute('UPDATE published_scripts SET version=?,script_json=?,title=?,tags_json=?,authoring_job_id=? WHERE catalog_id=? AND user_id=?',
                    (version,json.dumps(script,ensure_ascii=False),script['script_meta']['title'],json.dumps(script['script_meta']['tags'],ensure_ascii=False),job_id,catalog_id,user_id))
            else:
                result = self.catalog.publish(user_id,script,script['script_meta']['title'],script['script_meta']['tags'],authoring_job_id=job_id)
                catalog_id,version = result['catalog_id'],result['version']
            connection.execute('INSERT OR IGNORE INTO script_revisions VALUES (?,?,?,?,?)',
                               (catalog_id,version,user_id,json.dumps(script,ensure_ascii=False),utc_now()))
            self.update(job_id,status='published',result_json=json.dumps(result,ensure_ascii=False))
            return result

    def revisions(self, user_id, catalog_id):
        self.catalog.resolve(user_id,catalog_id)
        with self.store._connect() as connection:
            return [dict(row) for row in connection.execute('SELECT catalog_id,version,created_at FROM script_revisions WHERE user_id=? AND catalog_id=? ORDER BY created_at DESC',(user_id,catalog_id))]
