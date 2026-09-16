<script setup lang="ts">
import { ref, useId } from "vue";
import { Info } from "@lucide/vue";

defineProps<{
  label: string;
}>();

const tipId = useId();
const open = ref(false);

function toggle(event: MouseEvent) {
  const btn = event.currentTarget as HTMLButtonElement;
  if (open.value) {
    open.value = false;
    btn.blur();
    return;
  }
  open.value = true;
}

function onBlur() {
  open.value = false;
}
</script>

<template>
  <button
    type="button"
    class="info-tip"
    :class="{ 'is-open': open }"
    :aria-label="label"
    :aria-describedby="tipId"
    :aria-expanded="open"
    @click.stop="toggle"
    @blur="onBlur"
  >
    <Info aria-hidden="true" />
    <span :id="tipId" class="info-tip-text" role="tooltip">
      <slot />
    </span>
  </button>
</template>
