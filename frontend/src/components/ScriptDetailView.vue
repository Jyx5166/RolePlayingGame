<script setup lang="ts">
import { ArrowLeft, ArrowRight, BookOpen, Check, Users } from "@lucide/vue";
import { rolePortrait, scriptCover } from "../script-artwork";
import type { ScriptPreview } from "../scripts";
import "../script-library.css";

withDefaults(defineProps<{ script: ScriptPreview; tags: string[]; source?: string; busy?: boolean; error?: string; preparing?: boolean; selectedRole?: string }>(), { source: "", busy: false, error: "", preparing: false, selectedRole: "" });
defineEmits<{ back: []; choose: []; edit: [] }>();
</script>

<template>
  <div class="script-detail">
    <nav class="detail-breadcrumb" aria-label="当前位置"><button type="button" :disabled="busy" @click="$emit('back')"><ArrowLeft :size="18" aria-hidden="true" />返回剧本库</button><span class="detail-breadcrumb-divider"></span><span>新建游戏</span><span aria-hidden="true">›</span><span>{{ preparing ? '选择角色' : '剧本详情' }}</span></nav>
    <div class="detail-layout">
      <article class="detail-story">
        <div class="detail-cover"><img :src="scriptCover(script.script_id)" :alt="`${script.title}封面`" /><span class="detail-case-stamp">CASE FILE<br />{{ source === 'imported' ? '我的剧本' : '故事档案' }}</span></div>
        <div class="detail-story-content">
          <span v-if="source" class="detail-source">{{ source === 'builtin' ? '内置剧本' : '我的剧本' }}</span><h2>{{ script.title }}</h2>
          <div class="detail-facts"><div class="detail-tags"><span v-for="tag in tags" :key="tag">{{ tag }}</span></div><div class="detail-numbers"><span><Users :size="22" aria-hidden="true" />{{ script.role_count }} 位角色</span><span><BookOpen :size="22" aria-hidden="true" />{{ script.total_stages }} 幕故事</span></div></div>
          <section class="detail-synopsis"><h3>故事简介</h3><p>{{ script.story_background }}</p></section>
          <section class="detail-characters"><h3>可选角色</h3><div class="detail-portrait-grid"><div v-for="role in script.playable_roles" :key="role.role_id" class="detail-character" :class="{ selected: selectedRole === role.role_id }"><img :src="rolePortrait(role.role_id)" alt="" loading="lazy" /><div><strong>{{ role.role_name }}</strong><span>{{ role.public_identity }}</span></div><Check v-if="selectedRole === role.role_id" class="detail-character-selected" :size="18" aria-label="已选择" /></div></div></section>
          <button v-if="source === 'imported' && !preparing" class="catalog-edit" :disabled="busy" @click="$emit('edit')">编辑并发布新版本 <ArrowRight :size="14" aria-hidden="true" /></button>
        </div>
      </article>
      <aside class="detail-preparation" aria-label="入场准备">
        <h2>准备开始</h2><div class="detail-gold-rule"></div>
        <ol class="detail-steps"><li class="complete"><span class="detail-step-number">01</span><div><strong>剧本确认</strong><p>已查看剧本详情</p></div><Check :size="19" class="detail-step-check" aria-label="已完成" /></li><li :class="{ current: preparing }"><span class="detail-step-number">02</span><div><strong>选择角色</strong><p>从不同视角进入故事</p></div><span class="detail-step-circle"></span></li><li><span class="detail-step-number">03</span><div><strong>开始调查</strong><p>通过证词与线索推进调查</p></div><span class="detail-step-circle"></span></li></ol>
        <div class="detail-ready"><p>{{ preparing ? '选择你的角色，其余角色将由角色 Agent 扮演。' : '先了解故事，再选择角色。' }}</p><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="detail-choose" type="button" :disabled="busy" @click="$emit('choose')">{{ busy ? '正在准备…' : '选择角色' }}<ArrowRight :size="20" aria-hidden="true" /></button><button class="detail-return" type="button" :disabled="busy" @click="$emit('back')">返回剧本库</button></div>
      </aside>
    </div>
  </div>
</template>
