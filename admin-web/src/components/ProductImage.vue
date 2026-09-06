<template>
  <button ref="trigger" class="product-list-thumb product-image-trigger" type="button" :disabled="!ready" :aria-label="ready ? `放大查看${name}` : '产品图片未上传'" @click.stop="openPreview">
    <img v-if="src && !failed" v-show="ready" :key="src" class="product-list-image" :src="src" alt="" @load="ready = true" @error="fail" />
    <svg v-if="!ready" viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" /><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" /></svg>
  </button>
  <dialog ref="dialog" class="product-image-preview" :aria-label="`${name}图片预览`" @click.self="closePreview" @keydown.tab.prevent @cancel.prevent="closePreview" @close="restore">
    <button class="product-image-close" type="button" aria-label="关闭图片预览" autofocus @click="closePreview">×</button>
    <img v-if="previewing" :src="src || undefined" :alt="name" @error="fail" />
  </dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{ src: string | null; name: string }>();
const ready = ref(false);
const failed = ref(false);
const previewing = ref(false);
const dialog = ref<HTMLDialogElement>();
const trigger = ref<HTMLButtonElement>();
let previousOverflow: string | undefined;

function restore() {
  previewing.value = false;
  if (previousOverflow !== undefined) {
    document.body.style.overflow = previousOverflow;
    previousOverflow = undefined;
  }
}
function closePreview() {
  const wasOpen = dialog.value?.open;
  if (wasOpen) dialog.value?.close();
  restore();
  if (wasOpen) trigger.value?.focus({ preventScroll: true });
}
function openPreview() {
  if (!ready.value || !dialog.value || dialog.value.open) return;
  previewing.value = true;
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  dialog.value.showModal();
}
function fail() {
  ready.value = false;
  failed.value = true;
  closePreview();
}
watch(() => props.src, () => {
  closePreview();
  ready.value = false;
  failed.value = false;
});
onBeforeUnmount(restore);
</script>

<style scoped>
.product-image-trigger { padding: 0; cursor: zoom-in; }
.product-image-trigger:disabled { cursor: default; opacity: 1; }
.product-image-trigger:focus-visible { outline: 2px solid var(--erp-blue); outline-offset: 2px; }
.product-image-preview { box-sizing: border-box; width: fit-content; max-width: calc(100vw - 40px); max-height: calc(100dvh - 40px); padding: 44px 16px 16px; overflow: auto; background: white; border: 1px solid var(--line); border-radius: 8px; }
.product-image-preview::backdrop { background: rgba(28, 36, 45, .65); }
.product-image-preview > img { display: block; max-width: min(900px, calc(100vw - 74px)); max-height: calc(100dvh - 104px); object-fit: contain; }
.product-image-close { position: absolute; top: 6px; right: 8px; width: 32px; height: 32px; padding: 0; color: var(--ink); font-size: 26px; line-height: 1; background: white; border: 0; border-radius: 4px; cursor: pointer; }
</style>
