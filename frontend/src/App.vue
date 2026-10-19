<script setup lang="ts">
import AppSidebar from "./components/AppSidebar.vue";
import AuthView from "./components/AuthView.vue";
import CaseRecordsView from "./components/CaseRecordsView.vue";
import ScriptLibraryView from "./components/ScriptLibraryView.vue";
import ScriptCreatorView from "./components/ScriptCreatorView.vue";
import PersonalCenterView from "./components/PersonalCenterView.vue";
import GamePreparationView from "./components/GamePreparationView.vue";
import GameWorkbenchView from './components/GameWorkbenchView.vue';
import { useRoute } from "vue-router";
import { useAuthStore } from "./stores/auth";
const route = useRoute();
const auth = useAuthStore();
</script>

<template>
  <Teleport to="#authView">
    <AuthView />
  </Teleport>
  <Teleport to="#appSidebar">
    <AppSidebar />
  </Teleport>
  <Teleport to="#recordsView">
    <CaseRecordsView />
  </Teleport>
  <Teleport to="#scriptLibraryView"><ScriptLibraryView v-if="auth.user && route.name === 'script-library'" /></Teleport>
  <Teleport to="#createView"><ScriptCreatorView v-if="auth.user && ['script-create', 'case-create'].includes(String(route.name))" /></Teleport>
  <Teleport to="#personalCenterView"><PersonalCenterView v-if="auth.user && route.name === 'personal-center'" /></Teleport>
  <Teleport to="#preparationView"><GamePreparationView v-if="auth.user && route.name === 'game-prepare'" /></Teleport>
  <Teleport to="#modernGameView"><GameWorkbenchView v-if="auth.user && route.name === 'game-detail'" :key="route.params.gameId as string" :game-id="Number(route.params.gameId)" /></Teleport>
</template>
