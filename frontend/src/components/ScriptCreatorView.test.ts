// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appEvents } from "../app-events";
import { rolePortrait, scriptCover } from "../script-artwork";
import ScriptCreatorView from "./ScriptCreatorView.vue";

const apiRequest = vi.hoisted(() => vi.fn());
const route = vi.hoisted(() => ({ query: {} as Record<string, string> }));
vi.mock("../runtime", () => ({ getApiClient: () => ({ request: apiRequest }) }));
vi.mock("vue-router", () => ({ useRoute: () => route }));
const draft = { script_meta: { script_id: "rainy_night_letter", title: "测试剧本", tags: ["悬疑"] } };
const reviewed = { script_id: "rainy_night_letter", title: "测试剧本", role_count: 3, total_stages: 2, ai_agent_count: 2,
  story_background: "一封迟来的信，让三位故人在雨夜重聚。", playable_roles: [{ role_id: "rnl_qin_he", role_name: "秦禾", public_identity: "收到信的记者" }] };
const fullDraft = { ...draft, opening: { title: "雨夜来信", content: "三位故人因一封旧信来到档案馆，各自与馆长有不同的往事。" },
  roles: [{ role_id: "rnl_qin_he", role_name: "秦禾", public_identity: "收到信的记者", hidden_goal: "寻找失踪姐姐", stage_knowledge: {
    stage_1: { blocks: [{ block_id: "private-1", content: "你曾经偷偷拿走一封信。" }] },
  } }], stage_flow: { stage_1: { title: "第一幕 · 信不见了", public_briefing: "馆长倒下，来信消失了。", public_tasks: ["核对每个人的行踪"], personal_tasks: { rnl_qin_he: "隐藏旧信的下落" }, dm_hosting: "请依次询问行踪。" } } };
const passedValidation = { passed: true, checks: [{ code: "structure", label: "剧本结构", status: "passed", message: "角色、分幕和线索引用完整。" }], errors: [], warnings: [] };
const importedReview = { ...reviewed, authoring_validation: passedValidation, semantic_required: false, semantic_review: { status: "not_run", summary: "导入校验不进行模型审稿。" } };
const aiReview = { ...reviewed, authoring_validation: passedValidation, semantic_required: true, semantic_review: { status: "passed", summary: "故事逻辑与人物信息边界审稿通过。" } };
const wrappers: VueWrapper[] = [];
function setup() { const wrapper = mount(ScriptCreatorView); wrappers.push(wrapper); return wrapper; }
function jsonFile(content = JSON.stringify(draft), size = 100) { return { name: "test.json", size, text: async () => content }; }
async function importFile(wrapper: VueWrapper, file = jsonFile()) {
  Object.defineProperty(wrapper.get('input[type="file"]').element, "files", { configurable: true, value: [file] });
  await wrapper.get('input[type="file"]').trigger("change");
  await flushPromises();
}
function mockReviewedJob() {
  let submitted: any;
  apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/authoring-jobs") { submitted = JSON.parse(String(options?.body)); return { job_id: "job-1", status: "queued" }; }
    if (path === "/api/v1/authoring-jobs/job-1") return { status: "preview", can_publish: true, draft: submitted.script || draft, preview: { ...reviewed, title: submitted.title } };
    if (path === "/api/v1/authoring-jobs/job-1/publish") return { catalog_id: "script-1" };
    if (path === "/api/v1/authoring-jobs/unrelated-old-job") return { mode: "ai", status: "failed", catalog_id: "other-script", draft: fullDraft, preview: aiReview, can_publish: false };
    if (path === "/api/v1/scripts/my-script/edit") return { script: draft, source_job_id: null };
    throw new Error(`unexpected request: ${path}`);
  });
  return () => submitted;
}
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount());
  apiRequest.mockReset(); route.query = {}; sessionStorage.clear(); vi.useRealTimers();
});

describe("ScriptCreatorView", () => {
  it("keeps an honest preview placeholder and accessible native file control before importing", async () => {
    const wrapper = setup();
    expect(wrapper.get(".script-creator-preview").text()).toContain("等待导入");
    expect(wrapper.get(".script-creator-preview-placeholder").text()).toContain("校验后查看剧本预览");
    expect(wrapper.find(".script-creator-cover").exists()).toBe(false);
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    expect(wrapper.get("#scriptCreatorTitle").attributes("disabled")).toBeDefined();
    expect(wrapper.get('input[type="file"]').attributes("hidden")).toBeUndefined();
    expect(wrapper.get('input[type="file"]').attributes("aria-label")).toBe("选择 JSON 剧本文件");
    await wrapper.get(".script-creator-publish").trigger("click");
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it("requires a reviewed preview, invalidates it after edits, and publishes without starting a game", async () => {
    const submitted = mockReviewedJob();
    const wrapper = setup();
    await importFile(wrapper);
    expect(wrapper.find(".script-creator-preview-placeholder").exists()).toBe(true);
    expect(wrapper.get(".script-creator-file-row").text()).toContain("已读取，待校验");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get(".script-creator-preview-title").text()).toBe("测试剧本");
    expect(wrapper.get(".script-creator-preview-status").text()).toBe("校验通过");
    expect(wrapper.get(".script-creator-cover").attributes("src")).toBe(scriptCover(reviewed.script_id));
    expect(wrapper.get(".script-creator-cast img").attributes("src")).toBe(rolePortrait("rnl_qin_he"));
    expect(wrapper.get(".script-creator-cast figcaption").text()).toContain("收到信的记者");
    expect(wrapper.get(".script-creator-preview-meta").text()).toBe("3 位角色2 幕故事");
    await wrapper.get("#scriptCreatorTitle").setValue("恐怖夜宴");
    expect(wrapper.find(".script-creator-preview-title").exists()).toBe(false);
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const navigate = vi.fn(); const stop = appEvents.on("navigation:view", navigate);
    await wrapper.get(".script-creator-publish").trigger("click");
    await flushPromises(); stop();
    expect(navigate).toHaveBeenCalledWith({ view: "library" });
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("games"))).toBe(false);
    expect(submitted().title).toBe("恐怖夜宴");
    expect(apiRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/authoring-jobs/job-1/publish");
    expect(sessionStorage.getItem("authoring:last")).toBeNull();
  });

  it("accepts a dropped JSON file and keeps adding/removing tags consistent with validation", async () => {
    const submitted = mockReviewedJob();
    const wrapper = setup();
    await wrapper.get(".script-creator-dropzone").trigger("drop", { dataTransfer: { files: [jsonFile()] } });
    await flushPromises();
    expect(wrapper.get("#scriptCreatorTitle").element).toHaveProperty("value", "测试剧本");
    expect(apiRequest).not.toHaveBeenCalled();
    await wrapper.get("#scriptCreatorTag").setValue("身份");
    await wrapper.get('button[aria-label="添加标签"]').trigger("click");
    expect(wrapper.findAll(".script-creator-tag-chip").map(chip => chip.text())).toEqual(["悬疑", "身份"]);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(submitted().tags).toEqual(["悬疑", "身份"]);
    await wrapper.get('button[aria-label="移除标签：悬疑"]').trigger("click");
    expect(wrapper.find(".script-creator-cover").exists()).toBe(false);
    await wrapper.get("#scriptCreatorTag").setValue("推理");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(submitted().tags).toEqual(["身份", "推理"]);
    expect(submitted().script.script_meta.tags).toEqual(["身份", "推理"]);
  });

  it.each([
    ["{bad json", 100, "JSON 格式无效"],
    ["[]", 100, "剧本必须是 JSON 对象"],
    [JSON.stringify(draft), 6 * 1024 * 1024, "剧本文件不能超过 5 MB"],
  ])("rejects unusable imports without implying validation passed", async (content, size, message) => {
    const wrapper = setup();
    await importFile(wrapper, jsonFile(String(content), Number(size)));
    expect(wrapper.get('[role="alert"]').text()).toBe(message);
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    expect(wrapper.find(".script-creator-file-check").exists()).toBe(false);
    expect(wrapper.get("#scriptCreatorTitle").attributes("disabled")).toBeDefined();
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it("does not bypass the displayed tag count limit with comma-separated additions", async () => {
    const wrapper = setup();
    await importFile(wrapper, jsonFile(JSON.stringify({ script_meta: { title: "标签边界", tags: Array.from({ length: 11 }, (_, index) => `类型${index}`) } })));
    await wrapper.get("#scriptCreatorTag").setValue("推理，密室");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain("最多 12 个标签");
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it("preserves AI polling and reveals only the returned validated draft", async () => {
    vi.useFakeTimers();
    let polls = 0; let submitted: any;
    apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/v1/authoring-jobs") { submitted = JSON.parse(String(options?.body)); return { job_id: "ai-1", status: "queued" }; }
      if (path === "/api/v1/authoring-jobs/ai-1") return ++polls === 1 ? { status: "generating" } : { status: "preview", can_publish: true, draft, preview: aiReview };
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper = setup();
    await wrapper.findAll(".script-creator-tabs button")[1]!.trigger("click");
    await wrapper.get("#scriptCreatorTitle").setValue("AI 雨夜故事");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain("请先填写创作主题");
    expect(apiRequest).not.toHaveBeenCalled();
    await wrapper.get("textarea").setValue("一封旧信让三位故人重逢，调查彼此不同的过去。");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get(".script-creator-preview-status").text()).toBe("正在创作草稿");
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    expect(wrapper.get("textarea").attributes("disabled")).toBeDefined();
    await vi.advanceTimersByTimeAsync(1000); await flushPromises();
    expect(submitted).toMatchObject({ mode: "ai", title: "AI 雨夜故事", script: null });
    expect(submitted.topic).toContain("旧信");
    expect(wrapper.get(".script-creator-preview-title").text()).toBe(reviewed.title);
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
    await wrapper.get("textarea").setValue("修改主题");
    expect(wrapper.find(".script-creator-cover").exists()).toBe(false);
  });

  it("preserves cancellation of an AI task and reports interruption without a successful preview", async () => {
    vi.useFakeTimers(); let cancelled = false;
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/authoring-jobs") return { job_id: "cancel-1", status: "generating" };
      if (path.endsWith("/cancel")) { cancelled = true; return {}; }
      if (path === "/api/v1/authoring-jobs/cancel-1") return cancelled ? { status: "interrupted", error: "创作已取消" } : { status: "generating" };
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper = setup();
    await wrapper.findAll(".script-creator-tabs button")[1]!.trigger("click");
    await wrapper.get("#scriptCreatorTitle").setValue("未完成故事");
    await wrapper.get("textarea").setValue("雨夜重逢");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    await wrapper.get(".script-creator-job-status button").trigger("click");
    await vi.advanceTimersByTimeAsync(1000); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("创作已取消");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    expect(wrapper.find(".script-creator-restore").exists()).toBe(true);
  });

  it("automatically restores a saved draft into the reviewed preview and preserves its publish identity", async () => {
    sessionStorage.setItem("authoring:last", "saved-1");
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/authoring-jobs/saved-1") return { status: "preview", can_publish: true, draft, preview: reviewed };
      if (path === "/api/v1/authoring-jobs/saved-1/publish") return { catalog_id: "restored" };
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper = setup();
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    await flushPromises();
    expect(wrapper.get(".script-creator-file-row").text()).toContain("已恢复的草稿");
    expect(wrapper.get("#scriptCreatorTitle").element).toHaveProperty("value", draft.script_meta.title);
    expect(wrapper.get(".script-creator-preview-title").text()).toBe(reviewed.title);
    await wrapper.get(".script-creator-publish").trigger("click"); await flushPromises();
    expect(apiRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/authoring-jobs/saved-1/publish");
  });

  it("loads an existing script and submits edits as a new version without publishing automatically", async () => {
    sessionStorage.setItem("authoring:last", "unrelated-old-job");
    route.query = { edit: "my-script" };
    const submitted = mockReviewedJob();
    const wrapper = setup(); await flushPromises();
    expect(wrapper.get(".script-creator-header h2").text()).toBe("编辑剧本 · 发布新版本");
    expect(wrapper.get(".script-creator-file-row").text()).toContain("编辑已发布剧本 · 新版本");
    expect(wrapper.find(".script-creator-revalidation-note").exists()).toBe(false);
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    await wrapper.get("#scriptCreatorTitle").setValue("修订后的剧本");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    expect(submitted()).toMatchObject({ catalog_id: "my-script", title: "修订后的剧本", source_job_id: null });
    expect(submitted().script.script_meta.title).toBe("修订后的剧本");
    expect(apiRequest.mock.calls.filter(([path]) => String(path).includes("unrelated-old-job"))).toHaveLength(1);
    expect(apiRequest.mock.calls.some(([path]) => path.endsWith("/publish"))).toBe(false);
  });

  it("retains a published AI script's source when editing it from the library", async () => {
    route.query={edit:"published-script"};sessionStorage.setItem("authoring:last","published-ai");let submitted:any;
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/published-ai"))return {job_id:"published-ai",mode:"ai",status:"published",catalog_id:"published-script",draft:fullDraft,preview:aiReview,can_publish:false};
      if(path==="/api/v1/scripts/published-script/edit")return {script:fullDraft,source_job_id:"published-ai"};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"published-revision",mode:"import",input:{source_job_id:submitted.source_job_id},status:"queued"};}
      if(path.endsWith("/published-revision"))return {job_id:"published-revision",mode:"import",input:{source_job_id:"published-ai"},status:"preview",catalog_id:"published-script",draft:submitted.script,preview:{...aiReview,semantic_review:{status:"passed",summary:"修订稿已重新审稿，故事逻辑与信息边界通过。"}},can_publish:true};
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-revalidation-note").text()).toBe("沿用故事设计，修订后重新校验并审稿。");
    await wrapper.get("#scriptCreatorTitle").setValue("已发布故事的新版本");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",catalog_id:"published-script",source_job_id:"published-ai",title:"已发布故事的新版本"});
    expect(wrapper.get(".script-creator-review").text()).toContain("修订稿已重新审稿");
    expect(wrapper.get(".script-creator-review").text()).not.toContain("未进行模型审稿");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
  });

  it("shows actual dynamic step progress and resumes polling after a refresh", async () => {
    vi.useFakeTimers(); sessionStorage.setItem("authoring:last", "running-1"); let polls=0;
    apiRequest.mockImplementation(async () => ++polls===1 ? { mode:"ai",input:{title:"恢复中的故事",topic:"民国报馆的旧案",tags:["推理"]},status: "generating", steps: [
      { step_id: "design", label: "故事设计", status: "completed" },
      { step_id: "role-rnl_qin_he", label: "角色本 · 秦禾", status: "running" },
      { step_id: "stage-1", label: "第一幕", status: "pending" },
    ] } : { status: "preview", draft: fullDraft, preview: importedReview, can_publish: true, steps: [
      { step_id: "design", label: "故事设计", status: "completed" },
      { step_id: "role-rnl_qin_he", label: "角色本 · 秦禾", status: "completed" },
      { step_id: "stage-1", label: "第一幕", status: "completed" },
    ] });
    const wrapper=setup(); await flushPromises();
    expect(wrapper.get(".script-creator-progress").text()).toContain("已完成 1 / 3 步");
    expect(wrapper.findAll('.script-creator-tabs button')[1]!.attributes('aria-pressed')).toBe('true');
    expect((wrapper.get('#scriptCreatorTitle').element as HTMLInputElement).value).toBe('恢复中的故事');
    expect((wrapper.get('#scriptCreatorTopic').element as HTMLTextAreaElement).value).toBe('民国报馆的旧案');
    expect(wrapper.get(".script-creator-progress .is-running").text()).toContain("角色本 · 秦禾进行中");
    expect(wrapper.get(".script-creator-progress .is-pending").text()).toContain("第一幕待开始");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    await vi.advanceTimersByTimeAsync(1000); await flushPromises();
    expect(wrapper.get(".script-creator-progress").text()).toContain("已完成 3 / 3 步");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
    wrapper.unmount(); await vi.advanceTimersByTimeAsync(5000);
    expect(polls).toBe(2);
  });

  it("restores the original AI brief when planning fails before a draft exists", async () => {
    sessionStorage.setItem('authoring:last','truncated-plan');
    apiRequest.mockResolvedValue({job_id:'truncated-plan',mode:'ai',status:'failed',can_publish:false,
      input:{title:'雨夜报馆',topic:'两位角色核对报馆记录。',tags:['推理']},draft:null,
      steps:[{step_id:'plan',label:'故事设计与真相',status:'failed',error:'输出被截断'}]});
    const wrapper=setup();await flushPromises();
    expect((wrapper.get('#scriptCreatorTitle').element as HTMLInputElement).value).toBe('雨夜报馆');
    expect((wrapper.get('#scriptCreatorTopic').element as HTMLTextAreaElement).value).toBe('两位角色核对报馆记录。');
    expect(wrapper.findAll('.script-creator-tabs button')[1]!.attributes('aria-pressed')).toBe('true');
    expect(wrapper.get('.script-creator-publish').attributes('disabled')).toBeDefined();
  });

  it("separates the public opening from folded private role books and stage content", async () => {
    sessionStorage.setItem("authoring:last", "preview-1");
    apiRequest.mockResolvedValue({ status: "preview", draft: fullDraft, preview: importedReview, can_publish: true });
    const wrapper=setup(); await flushPromises();
    expect(wrapper.get(".script-creator-opening").text()).toContain(fullDraft.opening.content);
    expect(wrapper.get(".script-creator-opening").text()).not.toContain(fullDraft.stage_flow.stage_1.public_briefing);
    expect(wrapper.get(".script-creator-role-books details").attributes("open")).toBeUndefined();
    expect(wrapper.get(".script-creator-stage-books details").attributes("open")).toBeUndefined();
    expect(wrapper.get(".script-creator-role-books").text()).toContain("你曾经偷偷拿走一封信。");
    expect(wrapper.get(".script-creator-stage-books").text()).toContain("隐藏旧信的下落");
    expect(wrapper.get(".script-creator-review").text()).toContain("未进行模型审稿");
    expect(wrapper.get(".script-creator-review").text()).not.toContain("全部通过");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
  });

  it.each([
    ["server gate", "preview", false, importedReview],
    ["missing server gate", "preview", undefined, importedReview],
    ["failed job", "failed", true, importedReview],
    ["structure failure", "preview", undefined, { ...importedReview, authoring_validation: { ...passedValidation, passed: false } }],
    ["semantic failure", "preview", undefined, { ...importedReview, semantic_review: { status: "failed", summary: "人物行踪矛盾。" } }],
  ])("blocks publishing for %s even when a draft preview exists", async (_label,status,can_publish,preview) => {
    sessionStorage.setItem("authoring:last", "blocked-1");
    apiRequest.mockResolvedValue({ status, can_publish, preview, draft: fullDraft });
    const wrapper=setup(); await flushPromises();
    expect(wrapper.find(".script-creator-preview-title").exists()).toBe(true);
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    expect(wrapper.find(".is-validated").exists()).toBe(false);
    await wrapper.get(".script-creator-publish").trigger("click");
    expect(apiRequest.mock.calls.some(([path])=>String(path).endsWith("/publish"))).toBe(false);
  });

  it("keeps a failed AI draft and its source for JSON revision and another model review", async () => {
    sessionStorage.setItem("authoring:last", "failed-1"); let submitted: any;
    apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if(path.endsWith("/failed-1"))return { status: "failed", mode: "ai", can_publish: false, draft: fullDraft,
        steps: [{ step_id: "semantic", label: "语义审校", status: "failed", error: "秦禾的行踪与开幕矛盾。" }],
        preview: { semantic_required: true, authoring_validation: passedValidation, semantic_review: { status: "failed", summary: "有一处需修订。", issues: [{ severity: "error", code: "timeline", message: "秦禾的行踪与开幕矛盾。" }] } } };
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"fixed-1",status:"queued"};}
      if(path.endsWith("/fixed-1"))return { status:"preview",mode:"import",input:{source_job_id:"failed-1"},can_publish:true,draft:submitted.script,preview:aiReview };
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-progress .is-failed").text()).toContain("秦禾的行踪与开幕矛盾。");
    expect(wrapper.get(".script-creator-review").text()).toContain("需修订秦禾的行踪与开幕矛盾。");
    expect(wrapper.get(".script-creator-opening").text()).toContain("雨夜来信");
    expect(wrapper.get("#scriptCreatorDraft").element).toHaveProperty("value",JSON.stringify(fullDraft,null,2));
    const fixed={...fullDraft,opening:{...fullDraft.opening,content:"秦禾在约定时间到达档案馆。"}};
    await wrapper.get("#scriptCreatorDraft").setValue("{unfinished");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("#scriptCreatorDraft").setValue(JSON.stringify(fixed));
    expect(wrapper.find(".script-creator-review").exists()).toBe(false);
    expect(wrapper.get(".script-creator-revalidation-note").text()).toBe("沿用故事设计，修订后重新校验并审稿。");
    expect(wrapper.text()).not.toContain("不进行模型审稿");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",source_job_id:"failed-1",script:fixed});
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
  });

  it("revalidates an edited generated draft instead of generating the story again", async () => {
    let submitted: any;let creates=0;
    apiRequest.mockImplementation(async (path:string,options?:RequestInit)=>{
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:`ai-${++creates}`,status:"queued"};}
      return {status:"preview",can_publish:true,draft:submitted.script || fullDraft,preview:aiReview};
    });
    const wrapper=setup();await wrapper.findAll(".script-creator-tabs button")[1]!.trigger("click");
    await wrapper.get("#scriptCreatorTitle").setValue("新故事");await wrapper.get("#scriptCreatorTopic").setValue("旧信与重逢");
    await wrapper.get("form").trigger("submit");await flushPromises();
    await wrapper.get("#scriptCreatorTitle").setValue("修改草稿标题");
    expect(wrapper.get(".script-creator-tabs button").attributes("aria-pressed")).toBe("true");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",source_job_id:"ai-1",script:{script_meta:{title:"修改草稿标题"}}});
  });

  it.each(["running","incomplete"])("retains partial review findings when a failed task reports %s", async (terminalReviewStatus) => {
    vi.useFakeTimers();sessionStorage.setItem("authoring:last","partial-review");let polls=0;
    const partialReview={...aiReview,semantic_review:{status:"running",summary:"公共开幕与角色本已审完，交叉逻辑审稿尚未完成。",issues:[{severity:"warning",code:"clue_disclosure",message:"角色本中有一条线索需要进一步核对。"}]}};
    apiRequest.mockImplementation(async()=>++polls===1
      ? {job_id:"partial-review",mode:"import",input:{source_job_id:"original-ai"},status:"validating",preview:partialReview,can_publish:false,steps:[{step_id:"review:cross",label:"交叉逻辑审稿",status:"running"}]}
      : {job_id:"partial-review",mode:"import",input:{source_job_id:"original-ai"},status:"failed",draft:fullDraft,preview:{...partialReview,semantic_review:{...partialReview.semantic_review,status:terminalReviewStatus}},can_publish:false,error:"交叉逻辑审稿输出被截断。",steps:[{step_id:"review:cross",label:"交叉逻辑审稿",status:"failed"}]});
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-review h5 .is-running").text()).toBe("审稿中");
    expect(wrapper.get(".script-creator-review").text()).toContain("公共开幕与角色本已审完");
    expect(wrapper.get(".script-creator-semantic-issues").text()).toContain("角色本中有一条线索需要进一步核对。");
    await vi.advanceTimersByTimeAsync(1000);await flushPromises();
    expect(wrapper.get(".script-creator-review h5 .is-incomplete").text()).toBe("审稿未完成");
    expect(wrapper.get(".script-creator-review").text()).not.toContain("未进行模型审稿");
    expect(wrapper.get(".script-creator-review").text()).toContain("公共开幕与角色本已审完");
    expect(wrapper.get(".script-creator-semantic-issues").text()).toContain("角色本中有一条线索需要进一步核对。");
    expect(wrapper.get('[role="alert"]').text()).toContain("交叉逻辑审稿输出被截断。");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
  });

  it.each(["title", "tag"])("retains the failed AI review source after changing only its %s", async (field) => {
    sessionStorage.setItem("authoring:last","failed-ai");let submitted:any;
    const failure={...aiReview,semantic_review:{status:"failed",summary:"关键线索与案发时间矛盾。"}};
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/failed-ai"))return {job_id:"failed-ai",mode:"ai",status:"failed",draft:fullDraft,preview:failure,can_publish:false};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"review-again",status:"queued",mode:"import",input:{source_job_id:submitted.source_job_id}};}
      return {job_id:"review-again",status:"failed",mode:"import",input:{source_job_id:"failed-ai"},draft:submitted.script,preview:failure,can_publish:false};
    });
    const wrapper=setup();await flushPromises();
    if(field==="title")await wrapper.get("#scriptCreatorTitle").setValue("改名后的故事");
    else {await wrapper.get("#scriptCreatorTag").setValue("身份");await wrapper.get('button[aria-label="添加标签"]').trigger("click");}
    expect(wrapper.get(".script-creator-revalidation-note").text()).toBe("沿用故事设计，修订后重新校验并审稿。");
    expect(wrapper.text()).not.toContain("不进行模型审稿");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",source_job_id:"failed-ai"});
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".script-creator-review").text()).toContain("关键线索与案发时间矛盾。");
  });

  it("clears AI provenance when a separate JSON file is imported", async () => {
    sessionStorage.setItem("authoring:last","failed-ai");let submitted:any;
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/failed-ai"))return {job_id:"failed-ai",mode:"ai",status:"failed",draft:fullDraft,preview:aiReview,can_publish:false};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"fresh-import",status:"queued",mode:"import",input:{source_job_id:null}};}
      return {job_id:"fresh-import",status:"preview",mode:"import",input:{source_job_id:null},draft:submitted.script,preview:importedReview,can_publish:true};
    });
    const wrapper=setup();await flushPromises();await importFile(wrapper);
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",source_job_id:null});
    expect(wrapper.get(".script-creator-review").text()).toContain("未进行模型审稿");
    expect(wrapper.get(".script-creator-revalidation-note").text()).toContain("不进行模型审稿");
  });

  it("starts a fresh AI story after switching away from an invalid older draft", async () => {
    sessionStorage.setItem("authoring:last","older-1");let submitted:any;
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/older-1"))return {mode:"ai",status:"preview",draft:fullDraft,preview:aiReview,can_publish:true};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"new-ai",status:"queued"};}
      return {status:"preview",draft:fullDraft,preview:importedReview,can_publish:true};
    });
    const wrapper=setup();await flushPromises();
    await wrapper.get("#scriptCreatorDraft").setValue("{invalid");
    await wrapper.findAll(".script-creator-tabs button")[1]!.trigger("click");
    await wrapper.get("#scriptCreatorTitle").setValue("另一段故事");
    expect(wrapper.find("#scriptCreatorTopic").exists()).toBe(true);
    await wrapper.get("#scriptCreatorTopic").setValue("全新的雨夜谜案");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"ai",source_job_id:null,script:null,title:"另一段故事"});
  });

  it("retains the publication target when restoring and revising an existing script version", async () => {
    sessionStorage.setItem("authoring:last","revision-1");let submitted:any;
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/revision-1"))return {status:"failed",catalog_id:"existing-script",draft:fullDraft,preview:importedReview,can_publish:false};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"revision-2",status:"queued",catalog_id:"existing-script"};}
      return {status:"preview",catalog_id:"existing-script",draft:submitted.script,preview:importedReview,can_publish:true};
    });
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-header h2").text()).toBe("编辑剧本 · 发布新版本");
    await wrapper.get("#scriptCreatorTitle").setValue("再次修订");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({catalog_id:"existing-script",mode:"import",title:"再次修订"});
  });

  it("resumes a derived AI revision on refresh and retains its source for the next edit", async () => {
    vi.useFakeTimers();route.query={edit:"same-script"};sessionStorage.setItem("authoring:last","same-revision");let polls=0;let submitted:any;
    apiRequest.mockImplementation(async(path:string,options?:RequestInit)=>{
      if(path.endsWith("/same-revision"))return ++polls===1
        ? {mode:"import",input:{source_job_id:"original-ai"},status:"validating",catalog_id:"same-script",steps:[{step_id:"semantic",label:"语义审校",status:"running"}]}
        : {mode:"import",input:{source_job_id:"original-ai"},status:"preview",catalog_id:"same-script",draft:fullDraft,preview:aiReview,can_publish:true};
      if(path==="/api/v1/authoring-jobs"){submitted=JSON.parse(String(options?.body));return {job_id:"next-revision",status:"queued"};}
      if(path.endsWith("/next-revision"))return {mode:"import",input:{source_job_id:submitted.source_job_id},status:"preview",catalog_id:"same-script",draft:submitted.script,preview:aiReview,can_publish:true};
      throw new Error(`unexpected request: ${path}`);
    });
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-progress .is-running").text()).toContain("语义审校");
    expect(apiRequest.mock.calls.some(([path])=>String(path).endsWith("/edit"))).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);await flushPromises();
    expect(wrapper.get(".script-creator-preview-title").text()).toBe(reviewed.title);
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeUndefined();
    expect(polls).toBe(2);
    await wrapper.get("#scriptCreatorTitle").setValue("刷新后修订");
    expect(wrapper.get(".script-creator-revalidation-note").text()).toBe("沿用故事设计，修订后重新校验并审稿。");
    await wrapper.get("form").trigger("submit");await flushPromises();
    expect(submitted).toMatchObject({mode:"import",catalog_id:"same-script",source_job_id:"same-revision",title:"刷新后修订"});
  });

  it("ignores a late successful poll after cancellation and retains the cancelled draft", async () => {
    let finishPoll!: (value: unknown)=>void;
    apiRequest.mockImplementation(async (path:string)=>{
      if(path==="/api/v1/authoring-jobs")return {job_id:"late-1",status:"generating"};
      if(path.endsWith("/cancel"))return {status:"interrupted",draft:fullDraft,steps:[{step_id:"opening",label:"独立开幕",status:"completed"}]};
      return new Promise(resolve=>{finishPoll=resolve;});
    });
    const wrapper=setup();await wrapper.findAll(".script-creator-tabs button")[1]!.trigger("click");
    await wrapper.get("#scriptCreatorTitle").setValue("取消中的故事");await wrapper.get("#scriptCreatorTopic").setValue("雨夜旧信");
    await wrapper.get("form").trigger("submit");await flushPromises();
    await wrapper.get(".script-creator-job-status button").trigger("click");await flushPromises();
    finishPoll({status:"preview",draft:fullDraft,preview:importedReview,can_publish:true});await flushPromises();
    expect(wrapper.get(".script-creator-preview-status").text()).toBe("创作已中断");
    expect(wrapper.get(".script-creator-opening").text()).toContain("雨夜来信");
    expect(wrapper.get(".script-creator-publish").attributes("disabled")).toBeDefined();
    expect(wrapper.find(".script-creator-cover").exists()).toBe(false);
  });

  it("does not let a late cancellation replace a newly imported draft", async () => {
    let finishPoll!:(value:unknown)=>void;let finishCancel!:(value:unknown)=>void;
    apiRequest.mockImplementation(async(path:string)=>{
      if(path==="/api/v1/authoring-jobs")return {job_id:"old-1",status:"generating"};
      if(path.endsWith("/cancel"))return new Promise(resolve=>{finishCancel=resolve;});
      return new Promise(resolve=>{finishPoll=resolve;});
    });
    const wrapper=setup();await importFile(wrapper);
    await wrapper.get("form").trigger("submit");await flushPromises();
    await wrapper.get(".script-creator-job-status button").trigger("click");
    finishPoll({status:"failed",draft:fullDraft,error:"创作未完成"});await flushPromises();
    const replacement={script_meta:{...draft.script_meta,title:"新导入的故事"}};
    await importFile(wrapper,jsonFile(JSON.stringify(replacement)));
    finishCancel({status:"interrupted",draft:fullDraft});await flushPromises();
    expect(wrapper.get("#scriptCreatorTitle").element).toHaveProperty("value","新导入的故事");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.get(".script-creator-preview-status").text()).toBe("等待校验");
  });

  it("stops polling a running restored task when the creator leaves the page", async () => {
    vi.useFakeTimers();sessionStorage.setItem("authoring:last","running-away");
    apiRequest.mockResolvedValue({status:"generating",steps:[{step_id:"design",label:"故事设计",status:"running"}]});
    const wrapper=setup();await flushPromises();wrapper.unmount();
    await vi.advanceTimersByTimeAsync(5000);await flushPromises();
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });

  it("never substitutes the first stage for a missing independent opening", async () => {
    sessionStorage.setItem("authoring:last","legacy-1");
    apiRequest.mockResolvedValue({status:"preview",draft:{...fullDraft,opening:null},preview:importedReview,can_publish:true});
    const wrapper=setup();await flushPromises();
    expect(wrapper.get(".script-creator-opening").text()).toContain("此草稿未提供独立开幕。");
    expect(wrapper.get(".script-creator-opening").text()).not.toContain(fullDraft.stage_flow.stage_1.public_briefing);
  });
});
