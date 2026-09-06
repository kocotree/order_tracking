<template>
  <nav class="order-pagination" :aria-label="label">
    <span class="order-page-total">共 {{ total }} 条</span>
    <button class="order-page-button order-page-arrow" type="button" aria-label="上一页" :disabled="loading || page <= 1" @click="emit('change', page - 1)">‹</button>
    <template v-for="(slot, index) in slots" :key="index">
      <span v-if="slot === '…'" class="order-page-ellipsis" data-page-slot>…</span>
      <button v-else class="order-page-button" data-page-slot :class="{ 'is-current': slot === page }" type="button" :aria-label="`第 ${slot} 页`" :aria-current="slot === page ? 'page' : undefined" :disabled="loading" @click="slot !== page && emit('change', slot)">{{ slot }}</button>
    </template>
    <button class="order-page-button order-page-arrow" type="button" aria-label="下一页" :disabled="loading || page >= pages" @click="emit('change', page + 1)">›</button>
  </nav>
</template>

<script setup lang="ts">
import { computed } from "vue";
const props = withDefaults(defineProps<{ page: number; total: number; loading?: boolean; label?: string }>(), { loading: false, label: "列表分页" });
const emit = defineEmits<{ change: [page: number] }>();
const pages = computed(() => Math.max(1, Math.ceil(props.total / 10)));
const range = (start: number, count: number) => Array.from({ length: count }, (_, index) => start + index);
const slots = computed<(number | "…")[]>(() => {
  const total = pages.value;
  if (total <= 7) return range(1, total);
  if (props.page <= 4) return [...range(1, 5), "…", total];
  if (props.page >= total - 3) return [1, "…", ...range(total - 4, 5)];
  return [1, "…", props.page - 1, props.page, props.page + 1, "…", total];
});
</script>
