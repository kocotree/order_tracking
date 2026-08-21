<template>
  <button
    class="data-grid-sort-button"
    :class="{ 'is-sorted': active, 'is-sort-desc': active && sortOrder === 'desc' }"
    type="button"
    :aria-label="`按${label}${active && sortOrder === 'asc' ? '降序' : '升序'}排序`"
    @click="$emit('sort', field)"
  >
    <span>{{ label }}</span>
    <span class="data-grid-sort-arrows" aria-hidden="true">
      <span class="data-grid-sort-arrow is-up"></span>
      <span class="data-grid-sort-arrow is-down"></span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ label: string; field: string; sortBy: string; sortOrder: "asc" | "desc" }>();
defineEmits<{ sort: [field: string] }>();

const active = computed(() => props.sortBy === props.field);
</script>
