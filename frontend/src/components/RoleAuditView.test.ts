// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RoleAuditView from './RoleAuditView.vue';

const request = vi.hoisted(()=>vi.fn());
vi.mock('../runtime',()=>({getApiClient:()=>({request})}));
afterEach(()=>{vi.restoreAllMocks();request.mockReset();});

describe('RoleAuditView',()=>{
  it('keeps the selected role logs when an older role response arrives late',async()=>{
    vi.spyOn(HTMLDialogElement.prototype,'showModal').mockImplementation(function(this:HTMLDialogElement){this.open=true;});
    let resolveOld:(value:any)=>void=()=>{};
    request.mockImplementation((path:string)=>{
      if(path.endsWith('/role-records'))return Promise.resolve({roles:[{role_id:'r1',role_name:'旧角色'},{role_id:'r2',role_name:'新角色'}]});
      if(path.includes('actor_role_id=r1'))return new Promise(resolve=>{resolveOld=resolve;});
      return Promise.resolve({items:[{tool_call_id:'current',tool_name:'新角色记录',status:'succeeded'}],next_offset:1,has_more:false});
    });
    const wrapper=mount(RoleAuditView,{props:{gameId:5}});await flushPromises();
    await wrapper.get('nav').findAll('button')[1]!.trigger('click');await flushPromises();
    resolveOld({items:[{tool_call_id:'old',tool_name:'过期角色记录',status:'succeeded'}],next_offset:1,has_more:false});await flushPromises();
    expect(wrapper.text()).toContain('新角色记录');
    expect(wrapper.text()).not.toContain('过期角色记录');
    wrapper.unmount();
  });
});
