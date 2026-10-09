<script setup lang="ts">
import AppSidebar from "./components/AppSidebar.vue";
import AuthView from "./components/AuthView.vue";
import CaseRecordsView from "./components/CaseRecordsView.vue";
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
</template>
